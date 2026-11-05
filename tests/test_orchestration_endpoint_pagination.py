from dataclasses import replace
import json
from pathlib import Path

import pytest

from alertissimo.data_layer.execution import (
    EndpointPaginationError,
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
                "page_size": {
                    "type": "integer",
                    "role": "pagination",
                    "auto_page_size": 2,
                },
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


def test_alerce_query_objects_contracts_activate_batched_page_pagination():
    registry = EndpointRegistry()
    executor = RegistryEndpointExecutor(registry=registry)

    for origin in ("lsst", "ztf"):
        spec = registry.resolve("alerce", origin, "query_objects")
        assert RegistryEndpointExecutor._page_parameters(spec) == ("page", "page_size")
        prepared = executor._auto_paginated_params(
            spec, {}, caller_supplied_page=False
        )
        assert prepared["page_size"] == 1000


def test_executor_exhausts_wrapper_pagination_as_one_logical_execution():
    transport = _WrapperTransport()

    result = _executor(transport).execute(
        "example", "lsst", "query_objects", {"ra": 10.0}
    )

    assert [item["oid"] for item in result.payload["items"]] == ["A", "B", "C"]
    assert result.payload["next"] is None
    assert result.payload["has_next"] is False
    assert transport.calls == [
        {"ra": 10.0, "page_size": 2},
        {"ra": 10.0, "page_size": 2, "page": 2},
    ]
    assert result.execution_provenance.params == {"ra": 10.0, "page_size": 2}
    assert result.execution_provenance.raw_size_bytes == 30


def test_executor_exhausts_bare_list_pages_when_client_strips_wrapper():
    transport = _ListTransport()

    result = _executor(transport).execute(
        "example", "lsst", "query_objects", {"ra": 10.0}
    )

    assert [item["oid"] for item in result.payload] == ["A", "B", "C", "D", "E"]
    assert transport.calls == [
        {"ra": 10.0, "page_size": 2},
        {"ra": 10.0, "page_size": 2, "page": 2},
        {"ra": 10.0, "page_size": 2, "page": 3},
    ]
    assert result.execution_provenance.raw_size_bytes == 15


def test_explicit_page_request_remains_one_page_and_keeps_provider_page_size_default():
    transport = _ListTransport()

    result = _executor(transport).execute(
        "example", "lsst", "query_objects", {"ra": 10.0, "page": 2}
    )

    assert [item["oid"] for item in result.payload] == ["C", "D"]
    assert transport.calls == [{"ra": 10.0, "page": 2}]
    assert result.execution_provenance.params == {"ra": 10.0, "page": 2}


class _CappedTransport:
    name = "fixture"

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def execute(self, spec, params, headers=None):
        self.calls.append((spec, dict(params), headers))
        return TransportResult(
            self.payload, method=spec.method, url=spec.url,
            status_code=200, content_type="application/json", raw_size_bytes=123,
        )


def _capped_executor(payload):
    transport = _CappedTransport(payload)
    return RegistryEndpointExecutor(transports={"rest": transport}), transport


@pytest.mark.parametrize("count", [3, 4])
def test_fink_json_ceiling_is_an_explicit_incomplete_failure(count):
    executor, transport = _capped_executor([{"i:objectId": "same"}] * count)

    # Repeated alerts still consume the cap. Counting distinct objects would
    # conceal the saturation and allow a truncated candidate population through.
    with pytest.raises(EndpointPaginationError, match=r"incomplete result.*fink/ztf/latests.*n=3"):
        executor.execute("fink", "ztf", "latests", {"class": "SN candidate", "n": 3})

    assert len(transport.calls) == 1  # no guessed cursor or automatic retry


def test_fink_default_ceiling_is_checked_after_physical_defaults_are_applied():
    executor, transport = _capped_executor([{}] * 100)

    with pytest.raises(EndpointPaginationError, match="n=100"):
        executor.execute("fink", "ztf", "latests", {"class": "SN candidate"})

    spec, params, _ = transport.calls[0]
    assert spec.method == "GET"
    assert spec.url == "https://api.ztf.fink-portal.org/api/v1/latests"
    assert params["n"] == 100
    assert params["output-format"] == "json"
    assert "stopdate" not in params


@pytest.mark.parametrize("n", [0, -1, True, None, 1.0, 1.5, "0", "bad"])
def test_invalid_result_limit_fails_before_transport(n):
    executor, transport = _capped_executor([])

    with pytest.raises(EndpointPaginationError, match="positive integer"):
        executor.execute("fink", "ztf", "latests", {"class": "SN candidate", "n": n})

    assert transport.calls == []


@pytest.mark.parametrize("payload", [[], [{"i:objectId": "A"}]])
def test_unsaturated_json_payload_and_provenance_are_preserved(payload):
    executor, transport = _capped_executor(payload)
    params = {"class": "SN candidate", "n": "2", "startdate": "2021-11-01", "stopdate": "2021-12-01"}

    result = executor.execute("fink", "ztf", "latests", params)

    assert result.payload is payload
    assert result.execution_provenance.status == "success"
    assert result.execution_provenance.params == transport.calls[0][1]
    assert result.execution_provenance.params.items() >= params.items()
    assert result.execution_provenance.raw_size_bytes == 123


@pytest.mark.parametrize("payload", [{}, {"error": "upstream failure"}, b"not JSON", None])
def test_capped_json_endpoint_cannot_succeed_with_an_unverifiable_shape(payload):
    executor, transport = _capped_executor(payload)

    with pytest.raises(EndpointPaginationError, match="expected a JSON array"):
        executor.execute("fink", "ztf", "latests", {"class": "SN candidate"})

    assert len(transport.calls) == 1


@pytest.mark.parametrize("output_format", ["csv", "parquet", "votable"])
def test_explicit_raw_exports_retain_one_response_behavior_without_a_count_guarantee(output_format):
    executor, transport = _capped_executor(b"opaque export bytes")

    result = executor.execute("fink", "ztf", "latests", {
        "class": "SN candidate", "n": 1, "output-format": output_format,
    })

    assert result.payload == b"opaque export bytes"
    assert len(transport.calls) == 1
    assert result.execution_provenance.params["output-format"] == output_format


def test_unmarked_physical_limits_keep_their_existing_bounded_behavior():
    payload = [{"i:objectId": "A"}, {"i:objectId": "B"}]
    executor, _ = _capped_executor(payload)

    result = executor.execute("fink", "ztf", "anomaly", {"n": 1})

    assert result.payload is payload


@pytest.mark.parametrize("kind", ["two-ceilings", "page-and-ceiling"])
def test_ambiguous_result_limit_declarations_fail_before_transport(kind):
    spec = EndpointRegistry().resolve("fink", "ztf", "latests")
    declarations = dict(spec.params)
    declarations["extra"] = {
        "role": "result_limit" if kind == "two-ceilings" else "pagination",
        "default": 1,
    }
    if kind == "page-and-ceiling":
        declarations["page"] = declarations.pop("extra")

    class Registry:
        def resolve(self, *args):
            return replace(spec, params=declarations)

    executor, transport = _capped_executor([])
    executor.registry = Registry()

    with pytest.raises(EndpointPaginationError, match="one ceiling on a non-paginated JSON array"):
        executor.execute("fink", "ztf", "latests", {"class": "SN candidate"})

    assert transport.calls == []


def test_recorded_latests_alerts_keep_partition_and_detection_identity_below_the_cap():
    from alertissimo.data_layer.runtime.record_builder import build_portfolios_from_execution

    fixture = Path(__file__).parent / "fixtures/fink/ztf/latests.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    executor, _ = _capped_executor(payload)
    params = {
        "class": "Early SN Ia candidate", "n": len(payload) + 1,
        "startdate": "2021-11-01", "stopdate": "2021-12-01",
    }

    result = executor.execute("fink", "ztf", "latests", params)
    portfolios = build_portfolios_from_execution(result, validate_semantic_model=True)

    expected_ids = {row["i:objectId"] for row in payload}
    assert len(expected_ids) < len(payload)  # immutable capture includes repeats
    assert len(portfolios) == len(expected_ids)
    observed_ids = set()
    observed_detections = set()
    for portfolio in portfolios:
        summaries = [record for record in portfolio.records if record.semantic_type == "summary@ztf:fink"]
        ids = {record.fields["identity.object_id"] for record in summaries}
        assert len(ids) == 1
        observed_ids.update(ids)
        observed_detections.update(
            record.fields["identity.source_id"]
            for record in portfolio.records if record.semantic_type == "measurement@ztf:fink"
        )
    assert observed_ids == expected_ids
    assert observed_detections == {row["i:candid"] for row in payload}

    # The same recorded rows at their request cap cannot prove exhaustion.
    with pytest.raises(EndpointPaginationError, match="incomplete result"):
        executor.execute("fink", "ztf", "latests", {**params, "n": len(payload)})
