from pathlib import Path

import pytest

from alertissimo.data_layer.execution import (
    EndpointRegistry,
    EndpointSpec,
    MissingEndpointCredentialError,
    RegistryEndpointExecutor,
    RestTransport,
    TransportResult,
)
from alertissimo.data_layer.representations import InternalExecutionId


REGISTRY = Path(__file__).parents[1] / "alertissimo/data_layer/providers"


def test_rest_transport_encodes_get_params_in_url_without_body(monkeypatch):
    raw = b'{"objects": ["ZTF1", "ZTF2"]}'
    captured = {}

    class Headers:
        @staticmethod
        def get_content_type():
            return "application/json"

    class Response:
        status = 200
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        @staticmethod
        def read():
            return raw

    def fake_urlopen(request):
        captured["request"] = request
        return Response()

    monkeypatch.setattr("alertissimo.data_layer.execution.transports.urlopen", fake_urlopen)
    spec = EndpointSpec(
        broker="example",
        origin="ztf",
        endpoint="objects",
        transport_kind="rest",
        method="GET",
        url="https://example.test/objects",
    )

    result = RestTransport().execute(spec, {"object_ids": "ZTF1,ZTF2", "limit": 2})

    request = captured["request"]
    assert request.method == "GET"
    assert request.data is None
    assert request.full_url == (
        "https://example.test/objects?object_ids=ZTF1%2CZTF2&limit=2"
    )
    assert result.payload == {"objects": ["ZTF1", "ZTF2"]}
    assert result.url == request.full_url
    assert result.raw_size_bytes == len(raw)


def test_registry_resolves_lasair_rest_endpoint():
    spec = EndpointRegistry(REGISTRY).resolve("lasair", "ztf", "object")

    assert spec.transport_kind == "rest"
    assert spec.method == "POST"
    assert spec.url == "https://lasair-ztf.lsst.ac.uk/api/object/"


def test_registry_resolves_antares_python_endpoint():
    spec = EndpointRegistry(REGISTRY).resolve("antares", "ztf", "get_by_ztf_object_id")

    assert spec.transport_kind == "python_client"
    assert spec.module == "antares_client.search"
    assert spec.client_method == "get_by_ztf_object_id"


def test_registry_resolves_alerce_transport_python_endpoint():
    spec = EndpointRegistry(REGISTRY).resolve("alerce", "ztf", "query_objects")

    assert spec.transport_kind == "python_client"
    assert spec.module == "alerce.core"
    assert spec.client == "Alerce"
    assert spec.client_method == "query_objects"
    assert spec.fixed_params == {"survey": "ztf"}


class FixtureTransport:
    name = "fixture"

    def __init__(self, payload):
        self.payload = payload

    def execute(self, spec, params, headers=None):
        assert params["lasair_added"] is True
        assert headers is not None
        return TransportResult(
            self.payload,
            method="POST",
            url=spec.url,
            status_code=200,
            content_type="application/json",
            sanitized_headers={"Authorization": "<redacted>"},
            raw_size_bytes=42,
        )


def test_executor_adds_fixed_params_after_validating_caller_params(tmp_path):
    registry = tmp_path / "alerce" / "ztf"
    registry.mkdir(parents=True)
    (registry / "endpoints.yaml").write_text(
        """broker: alerce
origin: ztf
transport_defaults:
  kind: python
  fixed_params: {survey: ztf}
endpoints:
  object:
    transport: {module: example, method: object}
    params: {object_id: {required: true, type: string}}
"""
    )
    spec = EndpointRegistry(tmp_path).resolve("alerce", "ztf", "object")

    assert RegistryEndpointExecutor._validated_params(spec, {"object_id": "ZTF1"}) == {
        "object_id": "ZTF1", "survey": "ztf"
    }


def test_executor_preserves_payload_and_full_provenance():
    payload = {"objectId": "ZTF25aazqavg"}
    executor = RegistryEndpointExecutor(
        EndpointRegistry(REGISTRY),
        transports={"rest": FixtureTransport(payload)},
        execution_id_factory=lambda: InternalExecutionId("exec:fixed"),
    )
    result = executor.execute(
        "lasair", "ztf", "object", {"objectId": "ZTF25aazqavg"},
        headers={"Authorization": "Token secret-value"},
    )

    assert result.payload is payload
    assert result.internal_execution_id == InternalExecutionId("exec:fixed")
    assert result.execution_provenance.internal_execution_id == InternalExecutionId("exec:fixed")
    assert result.execution_provenance.broker == "lasair"
    assert result.execution_provenance.origin == "ztf"
    assert result.execution_provenance.endpoint == "object"
    assert result.execution_provenance.status == "success"
    assert result.execution_provenance.transport == "fixture"
    assert result.execution_provenance.method == "POST"
    assert result.execution_provenance.url == "https://lasair-ztf.lsst.ac.uk/api/object/"
    assert result.execution_provenance.params == {"objectId": "ZTF25aazqavg", "lasair_added": True}
    assert result.execution_provenance.response_status_code == 200
    assert result.execution_provenance.response_content_type == "application/json"
    assert result.execution_provenance.raw_size_bytes == 42
    assert result.execution_provenance.sanitized_headers["Authorization"] == "<redacted>"
    assert "secret-value" not in repr(result.execution_provenance)
    assert "secret-value" not in repr(result)


class CapturingTransport:
    name = "capture"

    def __init__(self):
        self.calls = []

    def execute(self, spec, params, headers=None):
        self.calls.append((spec, params, headers))
        return TransportResult(payload={}, sanitized_headers=headers or {})


@pytest.mark.parametrize(
    ("origin", "variable"),
    (("ztf", "LASAIR_ZTF_TOKEN"), ("lsst", "LASAIR_LSST_TOKEN")),
)
def test_executor_resolves_lasair_raw_token_from_origin_environment(
    monkeypatch, origin, variable
):
    monkeypatch.delenv("LASAIR_ZTF_TOKEN", raising=False)
    monkeypatch.delenv("LASAIR_LSST_TOKEN", raising=False)
    monkeypatch.setenv(variable, "raw-secret")
    transport = CapturingTransport()
    executor = RegistryEndpointExecutor(
        EndpointRegistry(REGISTRY), transports={"rest": transport}
    )

    result = executor.execute("lasair", origin, "object", {"objectId": "ID1"})

    assert transport.calls[0][2] == {"Authorization": "Token raw-secret"}
    assert result.execution_provenance.sanitized_headers == {
        "Authorization": "<redacted>"
    }
    assert "raw-secret" not in repr(result)


def test_explicit_header_overrides_environment(monkeypatch):
    monkeypatch.setenv("LASAIR_ZTF_TOKEN", "environment-secret")
    transport = CapturingTransport()
    executor = RegistryEndpointExecutor(
        EndpointRegistry(REGISTRY), transports={"rest": transport}
    )

    executor.execute(
        "lasair", "ztf", "object", {"objectId": "ID1"},
        headers={"Authorization": "Token explicit-secret"},
    )

    assert transport.calls[0][2] == {"Authorization": "Token explicit-secret"}


def test_missing_required_credential_fails_before_transport(monkeypatch):
    monkeypatch.delenv("LASAIR_ZTF_TOKEN", raising=False)
    transport = CapturingTransport()
    executor = RegistryEndpointExecutor(
        EndpointRegistry(REGISTRY), transports={"rest": transport}
    )

    with pytest.raises(MissingEndpointCredentialError, match="LASAIR_ZTF_TOKEN") as error:
        executor.execute("lasair", "ztf", "object", {"objectId": "ID1"})

    assert transport.calls == []
    assert "Token " not in str(error.value)


def test_public_endpoint_does_not_resolve_headers():
    transport = CapturingTransport()
    executor = RegistryEndpointExecutor(
        EndpointRegistry(REGISTRY), transports={"rest": transport}
    )

    executor.execute("fink", "ztf", "objects", {"objectId": "ZTF1"})

    assert transport.calls[0][2] is None
