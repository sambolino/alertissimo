"""Lasair classification uses context-bearing object routes; offline captures."""

from copy import deepcopy
from collections import Counter
from itertools import count
import json
from pathlib import Path

import pytest

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import EndpointRegistry, ExecutionResult
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.data_layer.runtime.serialization import portfolio_to_dict
from alertissimo.dsl import SurfaceLoweringError
from alertissimo.orchestration.binding import bind_endpoint_calls
from alertissimo.orchestration.ir import GetClassificationStep, GetCrossmatchStep, Source, TargetSelector
from alertissimo.orchestration.planner import plan_step
from alertissimo.orchestration.runtime import EndpointPlan, EndpointPlanRef, WorkflowExecutionError
from alertissimo.orchestration.normalization import summary_object_identity
from alertissimo.orchestration.validation import validate_step_capabilities


ROOT = Path(__file__).parent / "fixtures/lasair"
CASES = {
    "ztf": ("ZTF20acpwljl", "capture_20260813T110413Z", "objects", "objectIds"),
    "lsst": ("313761042336317573", "capture_20260813T140948Z", "object", "objectId"),
}


def fixture(origin, name):
    return json.loads((ROOT / origin / CASES[origin][1] / f"{name}.json").read_text())


def get(origin, *, classifier=None, ids=None):
    return GetClassificationStep(
        sources=[Source(broker="lasair", origin=origin)], classifier=classifier,
        target=TargetSelector(ids=ids, kind="object") if ids is not None else None,
    )


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


@pytest.mark.parametrize("origin", ["ztf", "lsst"])
@pytest.mark.parametrize("classifier", [None, "sherlock"])
@pytest.mark.parametrize("count_ids", [1, 2])
def test_unique_rich_context_route_preserves_its_native_cardinality(graph, origin, classifier, count_ids):
    oid, _, endpoint, parameter = CASES[origin]
    ids = [oid] if count_ids == 1 else [oid, "second-object"]
    step = get(origin, classifier=classifier, ids=ids)
    plan, = plan_step(step, graph)
    assert plan.endpoint == endpoint and plan.required
    assert plan.parameter_sources == {parameter: ("target", "ids")}
    assert EndpointPlan.model_validate_json(plan.model_dump_json()) == plan
    calls = bind_endpoint_calls(step, plan, EndpointRegistry())
    expected = [",".join(ids)] if origin == "ztf" else ids
    assert [call.params for call in calls] == [{parameter: value} for value in expected]
    if origin == "lsst":
        assert all(call.endpoint_spec.params["lasair_added"]["default"] is True for call in calls)


class Executor:
    def __init__(self, origin, *, fail_objects=False):
        self.origin, self.fail_objects = origin, fail_objects
        self.calls, self.ids = [], count()

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        assert (broker, origin) == ("lasair", self.origin)
        oid = CASES[origin][0]
        assert endpoint in {"object", "objects"}
        parameter = "objectIds" if endpoint == "objects" else "objectId"
        assert dict(params or {}) == {parameter: oid}
        self.calls.append(endpoint)
        if endpoint == "objects" and self.fail_objects:
            raise RuntimeError("object context request failed")
        name = "objects_plural" if endpoint == "objects" else (
            "object_default" if origin == "ztf" else "object_with_context"
        )
        return ExecutionResult(payload=deepcopy(fixture(origin, name)), execution_provenance=InternalExecutionProvenance(
            internal_execution_id=InternalExecutionId(f"lasair-class:{next(self.ids)}"),
            broker=broker, origin=origin, endpoint=endpoint, params=dict(params or {}),
        ))


@pytest.mark.parametrize("origin", ["ztf", "lsst"])
@pytest.mark.parametrize("classifier", [None, "sherlock"])
def test_recorded_class_description_and_reliability_survive_public_retrieval(graph, origin, classifier):
    oid, _, endpoint, _ = CASES[origin]
    suffix = "" if classifier is None else f" from {classifier}"
    source = f"object {oid} from {origin} via lasair\nwith classification{suffix} via lasair\n"
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    check, = (c for c in validation.capabilities.checks if c.subject == "requirement")
    assert {name for item in check.evidence for name in item.endpoints} == {endpoint}
    executor = Executor(origin)
    result = execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    assert executor.calls == (["object", "objects"] if origin == "ztf" else ["object"])
    plan, = result.run.steps[1].endpoint_plans
    expected_reuse = EndpointPlanRef(step_index=0, plan_index=0) if origin == "lsst" else None
    assert plan.execution_reuse_from == expected_reuse
    portfolio, = result.portfolios
    assert summary_object_identity(portfolio) == (origin, oid)
    assertions = [r for r in portfolio.records if r.semantic_type == "classification@sherlock:lasair"]
    assert assertions
    for record in assertions:
        assert record.get("best.class") == "SN"
        assert record.get("best.score") == 2
        assert record.get("best.description")
        assert record.get("best.probability") is None
        provenance = portfolio.execution(record.internal_source.internal_execution_id)
        assert (provenance.broker, provenance.origin) == ("lasair", origin)
        assert provenance.endpoint in {"object", "objects"}


@pytest.mark.parametrize("origin", ["ztf", "lsst"])
def test_continuation_keeps_previous_material_and_all_survivor_records(graph, origin):
    oid = CASES[origin][0]
    executor = Executor(origin)
    first = execute_dsl(f"object {oid} from {origin} via lasair\n",
                        graph=graph, executor=executor, continue_from=None)
    snapshot = first.to_dict()
    second = execute_dsl("with classification via lasair\n", graph=graph, executor=executor, continue_from=first)
    second_snapshot = second.to_dict()
    third = execute_dsl("filter classification@sherlock:lasair.best.score >= 2\n",
                        graph=graph, executor=executor, continue_from=second)
    assert first.to_dict() == snapshot
    assert second.to_dict() == second_snapshot
    assert second.workflow.steps[:len(first.workflow.steps)] == first.workflow.steps
    assert third.workflow.steps[:len(second.workflow.steps)] == second.workflow.steps
    before, = second.portfolios
    after, = third.portfolios
    assert summary_object_identity(before) == summary_object_identity(after) == (origin, oid)

    def record_evidence(portfolio):
        # Replay re-normalizes saved payloads with fresh record UUIDs. Keep all
        # fields and full source attribution, including duplicate multiplicity.
        return Counter(json.dumps({key: value for key, value in record.items()
                                   if key != "internal_record_id"}, sort_keys=True)
                       for record in portfolio_to_dict(portfolio)["records"])

    assert record_evidence(after) == record_evidence(before)
    assert after.executions == before.executions
    # Within the rebuilt snapshot, Filter must retain the exact source records.
    rebuilt_before, = third.result.steps[len(second.workflow.steps) - 1].portfolios
    assert after.records == rebuilt_before.records
    assert executor.calls == (["object", "objects"] if origin == "ztf" else ["object"])


class SyntheticTnsExecutor:
    """Standalone synthetic typed-TNS case; no frozen capture is edited."""
    def __init__(self):
        self.ids = count()

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        assert (broker, origin) == ("lasair", "ztf")
        row = {"objectId": "ZTF20synthetic", "objectData": {
            "ramean": 120.0, "decmean": -6.0, "ncand": 2, "jdmin": 2459000.5, "jdmax": 2459001.5,
        }, "sherlock": {"classification": "AGN", "classificationReliability": 1}, "TNS": {"type": "SN Ia"}}
        return ExecutionResult(payload=row if endpoint == "object" else [row], execution_provenance=InternalExecutionProvenance(
            internal_execution_id=InternalExecutionId(f"synthetic-tns:{next(self.ids)}"),
            broker=broker, origin=origin, endpoint=endpoint, params=dict(params or {}),
        ))


def test_ztf_tns_selection_does_not_mix_it_with_sherlock(graph):
    result = execute_dsl("object ZTF20synthetic from ztf via lasair\nwith classification from tns via lasair\n",
                         graph=graph, executor=SyntheticTnsExecutor(), continue_from=None)
    classes = [r for p in result.portfolios for r in p.records if r.semantic_type.startswith("classification@")]
    assert {r.semantic_type for r in classes} == {"classification@tns:lasair"}
    assert {r.get("best.class") for r in classes} == {"SN Ia"}


@pytest.mark.parametrize("origin,classifier", [("ztf", "unknown"), ("lsst", "tns")])
def test_unmapped_producer_rejects_before_transport(graph, origin, classifier):
    executor = Executor(origin)
    with pytest.raises(SurfaceLoweringError):
        execute_dsl(f"object {CASES[origin][0]} from {origin} via lasair\n"
                    f"with classification from {classifier} via lasair\n",
                    graph=graph, executor=executor, continue_from=None)
    assert executor.calls == []


def test_missing_tns_type_in_the_capture_does_not_invent_a_classification(graph):
    result = execute_dsl(f"object {CASES['ztf'][0]} from ztf via lasair\n"
                         "with classification from tns via lasair\n",
                         graph=graph, executor=Executor("ztf"), continue_from=None)
    assert not any(r.semantic_type.startswith("classification@") for p in result.portfolios for r in p.records)


def test_failed_canonical_route_does_not_fall_back_to_sherlock(graph):
    executor = Executor("ztf", fail_objects=True)
    with pytest.raises(WorkflowExecutionError, match="object context request failed"):
        execute_dsl(f"object {CASES['ztf'][0]} from ztf via lasair\nwith classification via lasair\n",
                    graph=graph, executor=executor, continue_from=None)
    assert executor.calls == ["object", "objects"]


def test_sherlock_endpoints_and_crossmatch_routes_remain_registered(graph):
    for origin in CASES:
        assert "sherlock_object" in {endpoint.endpoint for endpoint in graph.endpoints_for("lasair", origin)}
        result = validate_step_capabilities(GetCrossmatchStep(sources=[Source(broker="lasair", origin=origin)]), graph)
        assert "sherlock_object" in {endpoint.endpoint for endpoint in result.candidates}
