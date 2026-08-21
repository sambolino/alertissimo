from alertissimo.data_layer.execution import (
    EndpointRegistry,
    EndpointSpec,
    RegistryEndpointExecutor,
    TransportResult,
)
from alertissimo.data_layer.representations import InternalExecutionId


class _Registry:
    def resolve(self, broker, origin, endpoint):
        assert (broker, origin, endpoint) == ("example", "lsst", "query_objects")
        return EndpointSpec(
            broker=broker,
            origin=origin,
            endpoint=endpoint,
            transport_kind="fixture",
            params={
                "ra": {"type": "number"},
                "page": {"type": "integer", "role": "pagination"},
                "page_size": {"type": "integer", "role": "pagination"},
            },
        )


class _WrapperTransport:
    name = "fixture"

    def __init__(self):
        self.calls = []

    def execute(self, spec, params, headers=None):
        del spec, headers
        params = dict(params)
        self.calls.append(params)
        page = params.get("page", 1)
        payloads = {
            1: {
                "items": [{"oid": "A"}, {"oid": "B"}],
                "page": 1,
                "next": 2,
                "has_next": True,
                "total": 3,
            },
            2: {
                "items": [{"oid": "C"}],
                "page": 2,
                "next": None,
                "has_next": False,
                "total": 3,
            },
        }
        return TransportResult(payloads[page], raw_size_bytes=10 * page)


class _ListTransport:
    """Mimic a client library that strips the provider pagination wrapper."""

    name = "fixture"

    def __init__(self):
        self.calls = []

    def execute(self, spec, params, headers=None):
        del spec, headers
        params = dict(params)
        self.calls.append(params)
        page = params.get("page", 1)
        payloads = {
            1: [{"oid": "A"}, {"oid": "B"}],
            2: [{"oid": "C"}, {"oid": "D"}],
            3: [{"oid": "E"}],
        }
        return TransportResult(payloads.get(page, []), raw_size_bytes=5)


def _executor(transport):
    return RegistryEndpointExecutor(
        _Registry(),
        transports={"fixture": transport},
        execution_id_factory=lambda: InternalExecutionId("execution:paginated"),
    )


def test_alerce_query_objects_contracts_activate_page_pagination():
    registry = EndpointRegistry()

    for origin in ("lsst", "ztf"):
        spec = registry.resolve("alerce", origin, "query_objects")
        assert RegistryEndpointExecutor._page_parameters(spec) == ("page", "page_size")


def test_executor_exhausts_wrapper_pagination_as_one_logical_execution():
    transport = _WrapperTransport()

    result = _executor(transport).execute(
        "example", "lsst", "query_objects", {"ra": 10.0}
    )

    assert [item["oid"] for item in result.payload["items"]] == ["A", "B", "C"]
    assert result.payload["next"] is None
    assert result.payload["has_next"] is False
    assert transport.calls == [{"ra": 10.0}, {"ra": 10.0, "page": 2}]
    assert result.execution_provenance.params == {"ra": 10.0}
    assert result.execution_provenance.raw_size_bytes == 30


def test_executor_exhausts_bare_list_pages_when_client_strips_wrapper():
    transport = _ListTransport()

    result = _executor(transport).execute(
        "example", "lsst", "query_objects", {"ra": 10.0}
    )

    assert [item["oid"] for item in result.payload] == ["A", "B", "C", "D", "E"]
    assert transport.calls == [
        {"ra": 10.0},
        {"ra": 10.0, "page": 2},
        {"ra": 10.0, "page": 3},
    ]
    assert result.execution_provenance.raw_size_bytes == 15


def test_explicit_page_request_remains_one_page():
    transport = _ListTransport()

    result = _executor(transport).execute(
        "example", "lsst", "query_objects", {"ra": 10.0, "page": 2}
    )

    assert [item["oid"] for item in result.payload] == ["C", "D"]
    assert transport.calls == [{"ra": 10.0, "page": 2}]
