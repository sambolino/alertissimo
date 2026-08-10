"""Tests for the physical endpoint executor boundary."""

from dataclasses import FrozenInstanceError
from dataclasses import replace
from email.message import Message
from types import ModuleType
from unittest.mock import patch
import sys

import pytest

from alertissimo.core.brokers.execution import (
    EndpointNotFoundError,
    EndpointRegistry,
    FixtureNotFoundError,
    FixtureTransport,
    EnvironmentCredentialResolver,
    ParameterValidationError,
    PythonClientTransport,
    RegistryEndpointExecutor,
    RestTransport,
    TransportNotConfiguredError,
    TransportResult,
    TomlCredentialResolver,
)
from alertissimo.core.brokers.execution.examples import (
    build_example_executor,
    execute_example_command,
)
from alertissimo.core.brokers.execution.examples.get_ZTF25aazqavg_from_antares_ztf import (
    run as run_antares_example,
)
from alertissimo.core.brokers.execution.examples.get_ZTF19acmdpyr_from_fink_ztf import (
    run as run_fink_example,
)
from alertissimo.core.brokers.execution.examples.get_ZTF25aazqavg_from_lasair_ztf import (
    run as run_lasair_example,
)
from alertissimo.core.portfolio import (
    InternalExecutionId,
    InternalPortfolioId,
    InternalRecordId,
)


@pytest.fixture(scope="module")
def registry():
    return EndpointRegistry()


def test_internal_ids_are_strongly_typed_and_immutable():
    execution_id = InternalExecutionId("exec:test")
    assert str(execution_id) == "exec:test"
    assert execution_id != InternalPortfolioId("exec:test")
    assert execution_id != InternalRecordId("exec:test")
    with pytest.raises(FrozenInstanceError):
        execution_id.value = "changed"


def test_registry_combines_endpoints_mappings_and_capabilities(registry):
    spec = registry.get("lasair", "ztf", "object")

    assert spec.transport_kind == "rest"
    assert spec.method == "POST"
    assert spec.url == "https://lasair-ztf.lsst.ac.uk/api/object/"
    assert set(spec.params) == {"objectId", "lasair_added"}
    assert {payload.name for payload in spec.payloads} == {"object", "candidates"}
    assert "summary@ztf:lasair.identity.object_id" in spec.semantic_paths
    assert "detection@ztf:lasair.identity.source_id" in spec.semantic_paths
    assert "findobject" in registry.capabilities_for("lasair")


def test_registry_normalizes_both_python_endpoint_styles(registry):
    antares = registry.get("antares", "ztf", "get_by_ztf_object_id")
    alerce = registry.get("alerce", "ztf", "query_object")

    assert antares.transport_kind == "python"
    assert antares.method == "python"
    assert antares.path == "antares_client.search.get_by_ztf_object_id"
    assert alerce.transport_kind == "python"
    assert alerce.method == "query_object"
    assert alerce.fixed_params == {"survey": "ztf"}


def test_executor_dispatches_fixture_and_preserves_payload(registry):
    payload = {"objectId": "ZTF25aazqavg", "candidates": [{"candid": 7}]}
    transport = FixtureTransport({("lasair", "ztf", "object"): payload})
    executor = RegistryEndpointExecutor(
        registry,
        {"rest": transport},
        execution_id_factory=lambda: InternalExecutionId("exec:fixed"),
    )

    result = executor.call(
        broker="lasair",
        origin="ztf",
        endpoint="object",
        params={"objectId": "ZTF25aazqavg"},
    )

    assert result.payload is payload
    assert result.internal_execution_id == InternalExecutionId("exec:fixed")
    assert result.execution_provenance.internal_execution_id == InternalExecutionId(
        "exec:fixed"
    )
    assert result.execution_provenance.broker == "lasair"
    assert result.execution_provenance.origin == "ztf"
    assert result.execution_provenance.endpoint == "object"
    assert result.execution_provenance.status == "success"
    assert result.execution_provenance.transport == "fixture"
    assert result.execution_provenance.elapsed_ms >= 0
    assert result.execution_provenance.finished_at >= result.execution_provenance.started_at
    assert result.execution_provenance.method == "POST"
    assert result.execution_provenance.url == "https://lasair-ztf.lsst.ac.uk/api/object/"
    assert result.execution_provenance.params == {
        "objectId": "ZTF25aazqavg",
        "lasair_added": True,
    }
    assert result.execution_provenance.response_status_code is None


def test_transport_result_controls_runtime_metadata(registry):
    transport = FixtureTransport({
        ("fink", "ztf", "objects"): lambda _spec, _params: TransportResult(
            payload=[],
            method="GET",
            url="https://fixture.invalid/objects",
            status_code=200,
            content_type="application/json",
            sanitized_headers={"x-request-id": "safe"},
            raw_size_bytes=2,
        )
    })
    result = RegistryEndpointExecutor(registry, {"rest": transport}).call(
        broker="fink",
        origin="ztf",
        endpoint="objects",
        params={"objectId": "ZTF-test"},
    )

    assert result.execution_provenance.sanitized_headers == {"x-request-id": "safe"}
    assert result.execution_provenance.response_status_code == 200
    assert result.execution_provenance.response_content_type == "application/json"
    assert result.execution_provenance.raw_size_bytes == 2


def test_rest_transport_executes_get_and_decodes_broker_json(registry):
    class FakeResponse:
        status = 200
        headers = Message()
        headers["Content-Type"] = "application/json; charset=utf-8"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'[{"i:objectId": "123"}]'

        def getcode(self):
            return self.status

        def geturl(self):
            return "https://api.ztf.fink-portal.org/api/v1/objects?objectId=123"

    def fake_urlopen(request, *, timeout):
        assert request.method == "GET"
        assert "objectId=123" in request.full_url
        assert "output-format=json" in request.full_url
        assert timeout == 5.0
        return FakeResponse()

    executor = RegistryEndpointExecutor(
        registry,
        {"rest": RestTransport(timeout=5.0)},
    )
    with patch(
        "alertissimo.core.brokers.execution.transports.rest.urlopen",
        fake_urlopen,
    ):
        response = executor.call(
            broker="fink",
            origin="ztf",
            endpoint="objects",
            params={"objectId": "123"},
        )

    assert response.payload == [{"i:objectId": "123"}]
    assert response.execution_provenance.response_status_code == 200
    assert response.execution_provenance.response_content_type == "application/json; charset=utf-8"
    assert response.execution_provenance.raw_size_bytes == 23


def test_rest_transport_uses_credentials_and_redacts_metadata(registry):
    class FakeResponse:
        status = 200
        headers = Message()
        headers["Content-Type"] = "application/json"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"objectId":"ZTF25aazqavg"}'

        def getcode(self):
            return self.status

        def geturl(self):
            return "https://lasair-ztf.lsst.ac.uk/api/object/"

    def fake_urlopen(request, *, timeout):
        assert request.get_header("Authorization") == "Token secret-value"
        return FakeResponse()

    transport = RestTransport(
        credential_resolver=EnvironmentCredentialResolver({
            "LASAIR_ZTF_TOKEN": "secret-value",
        }),
    )
    with patch(
        "alertissimo.core.brokers.execution.transports.rest.urlopen",
        fake_urlopen,
    ):
        response = RegistryEndpointExecutor(registry, {"rest": transport}).call(
            broker="lasair",
            origin="ztf",
            endpoint="object",
            params={"objectId": "ZTF25aazqavg"},
        )

    assert response.payload == {"objectId": "ZTF25aazqavg"}
    assert response.execution_provenance.sanitized_headers["Authorization"] == "<redacted>"
    assert "secret-value" not in repr(response.execution_provenance)


def test_toml_credential_resolver(tmp_path):
    path = tmp_path / "secrets.toml"
    path.write_text('LASAIR_ZTF_TOKEN = "from-toml"\n')
    headers = TomlCredentialResolver(path).resolve(
        broker="lasair",
        origin="ztf",
        endpoint="object",
    )
    assert headers == {"Authorization": "Token from-toml"}


def test_python_client_transport_preserves_client_payload(registry):
    payload = object()
    fake_client = ModuleType("fake_antares_client")

    def lookup(*, ztf_object_id):
        assert ztf_object_id == "ZTF25aazqavg"
        return payload

    fake_client.lookup = lookup
    spec = replace(
        registry.get("antares", "ztf", "get_by_ztf_object_id"),
        path="fake_antares_client.lookup",
    )
    with patch.dict(sys.modules, {"fake_antares_client": fake_client}):
        result = PythonClientTransport().execute(
            spec=spec,
            params={"ztf_object_id": "ZTF25aazqavg"},
        )

    assert result.payload is payload
    assert result.method == "python"
    assert result.content_type == "application/x-python-object"


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({}, "missing required parameter"),
        ({"objectId": "x", "surprise": 1}, "unknown parameter"),
        ({"objectId": 123}, "must have type 'string'"),
    ],
)
def test_executor_validates_physical_parameters(registry, params, message):
    executor = RegistryEndpointExecutor(
        registry,
        {"rest": FixtureTransport({("fink", "ztf", "objects"): []})},
    )
    with pytest.raises(ParameterValidationError, match=message):
        executor.call(
            broker="fink",
            origin="ztf",
            endpoint="objects",
            params=params,
        )


def test_executor_reports_lookup_and_dispatch_errors(registry):
    with pytest.raises(EndpointNotFoundError, match="unknown endpoint"):
        registry.get("lasair", "ztf", "missing")

    with pytest.raises(TransportNotConfiguredError, match="no transport configured"):
        RegistryEndpointExecutor(registry, {}).call(
            broker="fink",
            origin="ztf",
            endpoint="objects",
            params={"objectId": "x"},
        )

    with pytest.raises(FixtureNotFoundError, match="no fixture registered"):
        RegistryEndpointExecutor(
            registry,
            {"rest": FixtureTransport({})},
        ).call(
            broker="fink",
            origin="ztf",
            endpoint="objects",
            params={"objectId": "x"},
        )


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (
            "get ZTF19acmdpyr from fink ztf",
            [{"i:objectId": "ZTF19acmdpyr", "i:candid": 1}],
        ),
        (
            "get ZTF25aazqavg from lasair ztf",
            {"objectId": "ZTF25aazqavg", "candidates": []},
        ),
    ],
)
def test_provisional_example_commands(command, expected):
    result = execute_example_command(command, build_example_executor())
    assert result.payload == expected
    assert str(result.internal_execution_id).startswith("exec:")


@pytest.mark.parametrize(
    "run_example",
    [
        lambda: run_fink_example(build_example_executor()),
        lambda: run_lasair_example(build_example_executor()),
        lambda: run_antares_example(build_example_executor()),
    ],
)
def test_example_files_return_complete_execution_response(run_example):
    response = run_example()
    assert response.payload is not None
    assert isinstance(response.internal_execution_id, InternalExecutionId)
    assert response.execution_provenance.transport == "fixture"
