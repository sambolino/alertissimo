"""End-to-end candidate-set evolution through a local semantic FilterStep."""

from __future__ import annotations

from itertools import count

from alertissimo.data_layer.execution import EndpointRegistry, ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
)
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import compile_surface_to_ir, parse_surface_script
from alertissimo.orchestration.pipeline import execute_staged_workflow_run
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import CandidateInputRef


CLASSIFIER = "stamp_classifier_rubin_beta_20260421"
OBJECT_A = "170587117485817955"
OBJECT_B = "170587117485817956"


def _dsl(threshold: float) -> str:
    return f"""objects from lsst via alerce
    where classification@{CLASSIFIER}.best.class = "SN" and classification@{CLASSIFIER}.best.probability >= 0.5
    with classification from {CLASSIFIER}
    with lightcurve via fink
    filter detection@lsst:fink.quality.reliability >= {threshold}
    with classification from fink via fink
"""


def _alerce_row(oid: str, probability: float) -> dict:
    return {
        "class_name": "SN",
        "classifier_name": CLASSIFIER,
        "classifier_version": "2.0.2",
        "deltamjd": 18.0,
        "firstmjd": 61217.0,
        "lastmjd": 61235.0,
        "meandec": -48.48,
        "meanra": 62.45,
        "n_det": 16,
        "n_forced": 23,
        "n_non_det": 0,
        "oid": int(oid),
        "probability": probability,
        "ranking": 1,
        "sid": 1,
        "sigmadec": 4.0e-6,
        "sigmara": 4.0e-6,
        "stellar": None,
        "tid": 1,
    }


class _FixtureExecutor:
    def __init__(self, *, allow_downstream: bool = True):
        self.calls: list[tuple[str, str, str, dict]] = []
        self._ids = count(1)
        self.allow_downstream = allow_downstream

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        del headers
        params = dict(params or {})
        self.calls.append((broker, origin, endpoint, params))

        if (broker, origin, endpoint) == ("alerce", "lsst", "query_objects"):
            payload = [
                _alerce_row(OBJECT_A, 0.9),
                _alerce_row(OBJECT_B, 0.8),
            ]
        elif (broker, origin, endpoint) == ("fink", "lsst", "sources"):
            assert params["diaObjectId"] == f"{OBJECT_A},{OBJECT_B}"
            payload = [
                {
                    "r:diaObjectId": int(OBJECT_A),
                    "r:diaSourceId": 101,
                    "r:midpointMjdTai": 61235.0,
                    "r:band": "r",
                    "r:reliability": 0.91,
                },
                {
                    "r:diaObjectId": int(OBJECT_B),
                    "r:diaSourceId": 102,
                    "r:midpointMjdTai": 61235.1,
                    "r:band": "r",
                    "r:reliability": 0.40,
                },
            ]
        elif (broker, origin, endpoint) == ("fink", "lsst", "objects"):
            if not self.allow_downstream:
                raise AssertionError("downstream classification must not execute for empty candidates")
            assert params["diaObjectId"] == OBJECT_A
            payload = [
                {
                    "r:diaObjectId": int(OBJECT_A),
                    "f:main_label_crossmatch": "Unknown",
                }
            ]
        else:
            raise AssertionError(f"unexpected physical call: {broker}/{origin}/{endpoint}")

        return ExecutionResult(
            payload=payload,
            execution_provenance=InternalExecutionProvenance(
                internal_execution_id=InternalExecutionId(
                    f"execution:filter:{next(self._ids)}"
                ),
                broker=broker,
                origin=origin,
                endpoint=endpoint,
                params=params,
            ),
        )


def _portfolio_object_id(portfolio) -> str:
    values = {
        str(value)
        for record in portfolio.records
        if record.semantic_type.split("@", 1)[0] == "summary"
        for key, value in record.fields.items()
        if key == "identity.object_id" and value is not None
    }
    assert len(values) == 1
    return next(iter(values))


def _object_ids(step_output) -> tuple[str, ...]:
    found: list[str] = []
    for execution in step_output.executions:
        for portfolio in execution.portfolios:
            value = _portfolio_object_id(portfolio)
            if value not in found:
                found.append(value)
    return tuple(found)


def _planned(threshold: float):
    graph = build_capability_graph()
    workflow = compile_surface_to_ir(
        parse_surface_script(_dsl(threshold)),
        graph=graph,
        name="filter candidate flow",
    )
    return workflow, plan_workflow(workflow, graph)


def test_filter_becomes_runtime_candidate_view_and_downstream_binding_uses_survivors():
    workflow, run = _planned(0.8)

    assert [step.op for step in workflow.steps] == [
        "semantic_search",
        "get_classification",
        "get_lightcurve",
        "filter",
        "get_classification",
    ]
    assert run.steps[1].endpoint_plans[0].execution_reuse_from is not None
    assert run.steps[2].endpoint_plans[0].candidate_input_from == CandidateInputRef(
        step_index=0
    )
    assert run.steps[3].endpoint_plans == ()
    assert run.steps[3].candidate_input_from == CandidateInputRef(step_index=2)
    assert run.steps[4].endpoint_plans[0].candidate_input_from == CandidateInputRef(
        step_index=3
    )
    assert (
        run.steps[4].endpoint_plans[0].broker,
        run.steps[4].endpoint_plans[0].origin,
        run.steps[4].endpoint_plans[0].endpoint,
    ) == ("fink", "lsst", "objects")

    executor = _FixtureExecutor()
    staged = execute_staged_workflow_run(run, EndpointRegistry(), executor)

    assert [(broker, origin, endpoint) for broker, origin, endpoint, _ in executor.calls] == [
        ("alerce", "lsst", "query_objects"),
        ("fink", "lsst", "sources"),
        ("fink", "lsst", "objects"),
    ]
    assert staged.bindings[4].bound_calls[0].params == {"diaObjectId": OBJECT_A}

    assert _object_ids(staged.normalized.steps[2]) == (OBJECT_A, OBJECT_B)
    assert _object_ids(staged.normalized.steps[3]) == (OBJECT_A,)
    assert _object_ids(staged.normalized.steps[4]) == (OBJECT_A,)

    # A local filter is a semantic view, not a physical execution. It retains the
    # physical execution grouping of its source and selects the same Portfolio.
    assert staged.run.steps[3].execution_ids == ()
    assert staged.normalized.steps[3].executions[0].execution_id == (
        staged.normalized.steps[2].executions[0].execution_id
    )
    source_a = next(
        portfolio
        for portfolio in staged.normalized.steps[2].executions[0].portfolios
        if _portfolio_object_id(portfolio) == OBJECT_A
    )
    assert staged.normalized.steps[3].executions[0].portfolios[0] is source_a


def test_empty_filter_skips_downstream_provider_call_without_fabricating_execution():
    _workflow, run = _planned(1.1)
    executor = _FixtureExecutor(allow_downstream=False)

    staged = execute_staged_workflow_run(run, EndpointRegistry(), executor)

    assert [(broker, origin, endpoint) for broker, origin, endpoint, _ in executor.calls] == [
        ("alerce", "lsst", "query_objects"),
        ("fink", "lsst", "sources"),
    ]
    assert _object_ids(staged.normalized.steps[3]) == ()
    assert staged.bindings[4].bound_calls == ()
    assert staged.run.steps[4].state.value == "succeeded"
    assert staged.run.steps[4].execution_ids == ()
    assert staged.normalized.steps[4].executions == ()
