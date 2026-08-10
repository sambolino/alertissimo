from alertissimo.core.brokers.execution import RegistryEndpointExecutor
from alertissimo.core.brokers.execution.models import TransportResult
from alertissimo.core.portfolio import InternalExecutionId


class Fixture:
    name = "fixture"

    def __init__(self, payload):
        self.payload = payload

    def execute(self, *, spec, params):
        return TransportResult(
            payload=self.payload,
            method=spec.method,
            url=spec.url,
            sanitized_headers={"Authorization": "<redacted>"},
            status_code=200,
            content_type="application/json",
            raw_size_bytes=42,
        )


def test_executor_returns_raw_payload_and_canonical_execution_provenance():
    payload = {"objectId": "ZTF25aazqavg"}
    executor = RegistryEndpointExecutor(
        transports={"rest": Fixture(payload)},
        execution_id_factory=lambda: InternalExecutionId("exec:fixed"),
    )
    result = executor.call("lasair", "ztf", "object", objectId="ZTF25aazqavg")

    assert result.payload is payload
    assert result.internal_execution_id == InternalExecutionId("exec:fixed")
    provenance = result.execution_provenance
    assert provenance.internal_execution_id == InternalExecutionId("exec:fixed")
    assert (provenance.broker, provenance.origin, provenance.endpoint) == ("lasair", "ztf", "object")
    assert provenance.status == "success"
    assert provenance.transport == "fixture"
    assert provenance.method == "POST"
    assert provenance.url == "https://lasair-ztf.lsst.ac.uk/api/object/"
    assert provenance.params == {"objectId": "ZTF25aazqavg", "lasair_added": True}
    assert provenance.response_status_code == 200
    assert provenance.sanitized_headers["Authorization"] == "<redacted>"
    assert "secret-value" not in repr(provenance)
    assert "secret-value" not in repr(result)


def test_execution_id_factory_must_return_canonical_type():
    executor = RegistryEndpointExecutor(transports={"rest": Fixture({})}, execution_id_factory=lambda: "exec:bad")
    try:
        executor.call("lasair", "ztf", "object", objectId="ZTF25aazqavg")
    except TypeError as error:
        assert str(error) == "execution_id_factory must return InternalExecutionId"
    else:
        raise AssertionError("expected TypeError")
