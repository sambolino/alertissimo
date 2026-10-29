"""Declared offset pagination and existing one-page recipe compatibility."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from alertissimo.data_layer.execution import (
    EndpointPaginationError, EndpointRegistry, EndpointSpec, ExecutionPolicy,
    ExecutionPolicyLimitError, RegistryEndpointExecutor, TransportResult,
)
from alertissimo.data_layer.representations import InternalExecutionId
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.data_layer.runtime.record_builder import build_portfolios_from_execution
from alertissimo.orchestration.binding import bind_endpoint_calls
from alertissimo.orchestration.ir import ConeSearchStep, Source
from alertissimo.orchestration.normalization import summary_object_identity
from alertissimo.orchestration.planner import plan_step


def spec():
    return EndpointSpec("offline", "survey", "query", "fixture", params={
        "limit": {"type": "integer", "default": 2, "role": "pagination", "auto_page_size_max": 1000},
        "offset": {"type": "integer", "default": 0, "role": "pagination"},
        "conditions": {"type": "string"},
    }, method="POST")


class Registry:
    def __init__(self, endpoint_spec):
        self.spec = endpoint_spec

    def resolve(self, *args):
        return self.spec


class OffsetTransport:
    name = "fixture"

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute(self, endpoint_spec, params, headers=None):
        self.calls.append((dict(params), headers))
        offset, limit = params["offset"], params["limit"]
        payload = self.rows[offset:offset + limit]
        return TransportResult(payload, method="POST", url=endpoint_spec.url,
                               status_code=200, content_type="application/json", raw_size_bytes=10 + len(payload))


def executor(transport, endpoint_spec=None, *, max_pages=3):
    return RegistryEndpointExecutor(
        Registry(endpoint_spec or spec()), transports={"fixture": transport, "rest": transport},
        execution_id_factory=lambda: InternalExecutionId("execution:offsets"),
        policy=ExecutionPolicy(1000, max_pages, Path("fixture-policy.yaml")),
    )


@pytest.mark.parametrize("count,offsets", [(0, [0]), (1, [0]), (4, [0, 2, 4]), (5, [0, 2, 4])])
def test_offset_pages_merge_into_one_execution_and_exact_multiples_probe_an_empty_page(count, offsets):
    rows = [{"id": index} for index in range(count)]
    transport = OffsetTransport(rows)
    supplied = {"conditions": "id >= 0 ORDER BY id"}
    result = executor(transport).execute("offline", "survey", "query", supplied)
    assert result.payload == rows
    assert [params["offset"] for params, _ in transport.calls] == offsets
    assert all(params["limit"] == 2 and params["conditions"] == supplied["conditions"] for params, _ in transport.calls)
    assert supplied == {"conditions": "id >= 0 ORDER BY id"}
    assert result.execution_provenance.params == {**supplied, "limit": 2, "offset": 0}
    assert result.execution_provenance.raw_size_bytes == count + 10 * len(offsets)
    assert result.internal_execution_id == InternalExecutionId("execution:offsets")


@pytest.mark.parametrize("offset", [0, 2])
def test_explicit_offset_is_exactly_one_bounded_response(offset):
    rows = [{"id": index} for index in range(6)]
    transport = OffsetTransport(rows)
    result = executor(transport).execute("offline", "survey", "query", {"limit": 2, "offset": offset})
    assert result.payload == rows[offset:offset + 2]
    assert len(transport.calls) == 1


def test_page_policy_limit_refuses_to_return_a_successful_partial_population():
    transport = OffsetTransport([{"id": index} for index in range(6)])
    with pytest.raises(ExecutionPolicyLimitError, match="max_auto_pages=2"):
        executor(transport, max_pages=2).execute("offline", "survey", "query")
    assert [params["offset"] for params, _ in transport.calls] == [0, 2]


def test_transport_fixed_offset_is_not_overridden_by_automatic_paging():
    transport = OffsetTransport([{"id": index} for index in range(6)])
    fixed = replace(spec(), fixed_params={"offset": 2})
    result = executor(transport, fixed).execute("offline", "survey", "query")
    assert result.payload == [{"id": 2}, {"id": 3}]
    assert [params["offset"] for params, _ in transport.calls] == [2]


@pytest.mark.parametrize("value", [0, -1, True, None, 1.5, "2"])
def test_invalid_automatic_limit_fails_before_transport(value):
    transport = OffsetTransport([])
    with pytest.raises(EndpointPaginationError, match="positive integer"):
        executor(transport).execute("offline", "survey", "query", {"limit": value})
    assert transport.calls == []


def test_account_clamping_cannot_look_like_an_exhausted_short_page():
    transport = OffsetTransport([])
    with pytest.raises(EndpointPaginationError, match="auto_page_size_max=1000"):
        executor(transport).execute("offline", "survey", "query", {"limit": 1001})
    assert transport.calls == []
    # Explicit bounded calls retain the physical API's own limit handling.
    result = executor(transport).execute("offline", "survey", "query", {"limit": 1001, "offset": 0})
    assert result.payload == [] and len(transport.calls) == 1


@pytest.mark.parametrize("change", ["negative-offset", "invalid-ceiling", "missing-limit-role", "mixed-page-mode", "result-ceiling"])
def test_invalid_offset_contracts_fail_before_transport(change):
    declarations = {name: dict(contract) for name, contract in spec().params.items()}
    if change == "negative-offset":
        declarations["offset"]["default"] = -1
    elif change == "invalid-ceiling":
        declarations["limit"]["auto_page_size_max"] = True
    elif change == "missing-limit-role":
        declarations["limit"].pop("role")
    elif change == "mixed-page-mode":
        declarations["page"] = {"role": "pagination"}
    else:
        declarations["n"] = {"default": 100, "role": "result_limit"}
    transport = OffsetTransport([])
    with pytest.raises(EndpointPaginationError):
        executor(transport, replace(spec(), params=declarations)).execute("offline", "survey", "query")
    assert transport.calls == []


@pytest.mark.parametrize("problem", ["wrong-first-shape", "wrong-later-shape", "oversized", "cycle"])
def test_unverifiable_or_repeated_pages_raise_instead_of_returning_partial_rows(problem):
    class BadTransport(OffsetTransport):
        def execute(self, endpoint_spec, params, headers=None):
            self.calls.append((dict(params), headers))
            offset = params["offset"]
            if problem == "wrong-first-shape" or problem == "wrong-later-shape" and offset:
                payload = {"error": "query failed"}
            elif problem == "oversized":
                payload = [1, 2, 3]
            else:
                payload = [0, 1] if offset % 4 == 0 else [2, 3]
            return TransportResult(payload)

    transport = BadTransport([])
    with pytest.raises(EndpointPaginationError):
        executor(transport).execute("offline", "survey", "query")
    assert 1 <= len(transport.calls) <= 3


def test_unmarked_limit_and_offset_keep_legacy_single_response_behavior():
    declarations = {name: {key: value for key, value in contract.items() if key != "role"}
                    for name, contract in spec().params.items()}
    transport = OffsetTransport([{"id": index} for index in range(5)])
    result = executor(transport, replace(spec(), params=declarations)).execute("offline", "survey", "query")
    assert result.payload == [{"id": 0}, {"id": 1}]
    assert len(transport.calls) == 1


@pytest.mark.parametrize("origin,path,selected,expected_id", [
    ("ztf", "ztf/capture_20260813T110413Z/query_core.json", "objects.objectId,objects.ramean,objects.decmean,objects.ncand,objects.jdmin,objects.jdmax", "ZTF20acpwljl"),
    ("lsst", "lsst/capture_20260813T140948Z/query_object_qualified.json", "objects.diaObjectId", "313761042336317573"),
])
def test_lasair_recorded_query_response_retains_identity_authentication_and_form_transport(origin, path, selected, expected_id):
    payload = json.loads((Path(__file__).parent / "fixtures/lasair" / path).read_text())
    endpoint_spec = EndpointRegistry().resolve("lasair", origin, "query")
    transport = OffsetTransport(payload)
    endpoint_executor = executor(transport, endpoint_spec)
    result = endpoint_executor.execute("lasair", origin, "query", {
        "selected": selected, "tables": "objects", "conditions": f"1=1 ORDER BY {selected.split(',')[0]}", "limit": 1,
    }, headers={"Authorization": "Token fixture-only"})
    assert result.payload == payload
    assert [params["offset"] for params, _ in transport.calls] == [0, 1]
    assert all(headers == {"Authorization": "Token fixture-only"} for _, headers in transport.calls)
    assert result.execution_provenance.sanitized_headers["Authorization"] == "<redacted>"
    assert endpoint_spec.method == "POST" and endpoint_spec.request_encoding == "form"
    portfolios = build_portfolios_from_execution(result, validate_semantic_model=True)
    assert {summary_object_identity(portfolio) for portfolio in portfolios} == {(origin, expected_id)}


def test_existing_ztf_cone_supplement_retains_explicit_offset_and_one_call():
    step = ConeSearchStep(sources=[Source(broker="lasair", origin="ztf")], semantic_type="summary", ra=120, dec=-6, radius=30)
    _, supplement = plan_step(step, build_capability_graph())
    bound, = bind_endpoint_calls(step, supplement, EndpointRegistry(), runtime_values={"target_id": ("ZTF20acpwljl",)})
    assert bound.params["offset"] == 0 and bound.params["limit"] == 100
    assert bound.params["conditions"] == 'objects.objectId IN ("ZTF20acpwljl")'
    # Saturation of this explicit physical page must not activate auto paging.
    transport = OffsetTransport([{"row": index} for index in range(100)])
    result = executor(transport, bound.endpoint_spec).execute(
        "lasair", "ztf", "query", bound.params, headers={"Authorization": "Token fixture-only"},
    )
    assert len(result.payload) == 100 and len(transport.calls) == 1
