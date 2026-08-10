from pathlib import Path

import pytest

pytest.importorskip("yaml")

from alertissimo.core.brokers.execution import EndpointExecutor, EndpointRegistry


def test_registry_resolves_lasair_rest_endpoint():
    spec = EndpointRegistry().resolve("lasair", "ztf", "object")
    assert spec.transport_kind == "rest"
    assert spec.method == "POST"
    assert spec.path == "/api/object/"
    assert spec.url == "https://lasair-ztf.lsst.ac.uk/api/object/"
    assert "objectId" in spec.params


def test_registry_resolves_antares_python_endpoint():
    spec = EndpointRegistry().resolve("antares", "ztf", "get_by_ztf_object_id")
    assert spec.transport_kind == "python_client"
    assert spec.method == "python"
    assert spec.path == "antares_client.search.get_by_ztf_object_id"
    assert "ztf_object_id" in spec.params


def test_registry_resolves_alerce_transport_python_endpoint():
    spec = EndpointRegistry().resolve("alerce", "ztf", "query_object")
    assert spec.transport_kind == "python_client"
    assert spec.method == "python"
    assert spec.path == "alerce.core.Alerce.query_object"
    assert spec.fixed_params == {"survey": "ztf"}
    assert "oid" in spec.params


def test_executor_adds_fixed_params_after_validating_caller_params(tmp_path: Path):
    registry_file = tmp_path / "alerce" / "ztf" / "endpoints.yaml"
    registry_file.parent.mkdir(parents=True)
    registry_file.write_text(
        """broker: alerce
origin: ztf
transport_defaults:
  kind: python
  module: example
  client: Client
  fixed_params: {survey: ztf}
endpoints:
  query_object:
    transport: {method: query_object}
    params:
      oid: {required: true, type: string}
""",
        encoding="utf-8",
    )

    class RecordingTransport:
        def execute(self, spec, params, headers):
            assert params == {"oid": "ZTF1", "survey": "ztf"}
            return {"native": True}

    executor = EndpointExecutor(
        registry=EndpointRegistry(tmp_path),
        transports={"python_client": RecordingTransport()},
    )
    result = executor.execute("alerce", "ztf", "query_object", {"oid": "ZTF1"})
    assert result.payload == {"native": True}
    assert dict(result.provenance.params) == {"oid": "ZTF1", "survey": "ztf"}
