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


OBJECT_A = "ZTF21abfmbix"
OBJECT_B = "ZTF20acpwljl"
RA = 124.87996115142856
DEC = -6.0205001


def _dsl(threshold: float) -> str:
    return f"""objects from ztf via lasair
    inside ({RA}, {DEC}, 5arcsec)
    with lightcurve via fink
    filter detection@ztf:fink.quality.real_bogus >= {threshold}
    with lightcurve via lasair
"""


class _FixtureExecutor:
    def __init__(self, *, allow_downstream: bool = True):
        self.calls: list[tuple[str, str, str, dict]] = []
        self._ids = count(1)
        self.allow_downstream = allow_downstream

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        del headers
        params = dict(params or {})
        self.calls.append((broker, origin, endpoint, params))

        if (broker, origin, endpoint) == ("lasair", "ztf", "cone"):
            assert params == {"ra": RA, "dec": DEC, "radius": 5.0}
            payload = [
                {"object": OBJECT_A, "separation": 0.0},
                {"object": OBJECT_B, "separation": 0.5},
            ]
        elif (broker, origin, endpoint) == ("lasair", "ztf", "query"):
            assert params["conditions"] == (
                f'objects.objectId IN ("{OBJECT_A}","{OBJECT_B}")'
            )
            payload = [
                {
                    "objectId": object_id,
                    "ramean": 124.87996115142856,
                    "decmean": -6.0205001,
                    "ncand": detection_count,
                    "jdmin": 2459000.5,
                    "jdmax": 2459001.5,
                }
                for object_id, detection_count in ((OBJECT_A, 2), (OBJECT_B, 1))
            ]
        elif (broker, origin, endpoint) == ("fink", "ztf", "objects"):
            assert params["objectId"] == f"{OBJECT_A},{OBJECT_B}"
            payload = [
                {"i:objectId": OBJECT_A, "i:drb": 0.91},
                {"i:objectId": OBJECT_B, "i:drb": 0.40},
            ]
        elif (broker, origin, endpoint) == ("lasair", "ztf", "lightcurves"):
            if not self.allow_downstream:
                raise AssertionError(
                    "downstream Lasair lightcurve must not execute for empty candidates"
                )
            assert params["objectIds"] == OBJECT_A
            payload = [
                {
                    "objectId": OBJECT_A,
                    "candidates": [
                        {
                            "candid": 1,
                            "jd": 2459001.5,
                            "fid": 1,
                            "ra": 10.1,
                            "dec": -2.1,
                            "magpsf": 19.1,
                            "sigmapsf": 0.1,
                        }
                    ],
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
        "cone_search",
        "get_lightcurve",
        "filter",
        "get_lightcurve",
    ]
    assert run.steps[1].endpoint_plans[0].candidate_input_from == CandidateInputRef(
        step_index=0
    )
    assert (
        run.steps[1].endpoint_plans[0].broker,
        run.steps[1].endpoint_plans[0].origin,
        run.steps[1].endpoint_plans[0].endpoint,
    ) == ("fink", "ztf", "objects")
    assert run.steps[2].endpoint_plans == ()
    assert run.steps[2].candidate_input_from == CandidateInputRef(step_index=1)
    assert run.steps[3].endpoint_plans[0].candidate_input_from == CandidateInputRef(
        step_index=2
    )
    assert (
        run.steps[3].endpoint_plans[0].broker,
        run.steps[3].endpoint_plans[0].origin,
        run.steps[3].endpoint_plans[0].endpoint,
    ) == ("lasair", "ztf", "lightcurves")

    executor = _FixtureExecutor()
    staged = execute_staged_workflow_run(run, EndpointRegistry(), executor)

    assert [(broker, origin, endpoint) for broker, origin, endpoint, _ in executor.calls] == [
        ("lasair", "ztf", "cone"),
        ("lasair", "ztf", "query"),
        ("fink", "ztf", "objects"),
        ("lasair", "ztf", "lightcurves"),
    ]
    assert staged.bindings[3].bound_calls[0].params == {"objectIds": OBJECT_A}

    assert _object_ids(staged.normalized.steps[1]) == (OBJECT_A, OBJECT_B)
    assert _object_ids(staged.normalized.steps[2]) == (OBJECT_A,)
    assert _object_ids(staged.normalized.steps[3]) == (OBJECT_A,)

    # A local filter is a semantic view, not a physical execution. It retains the
    # physical execution grouping of its source and selects the same Portfolio.
    assert staged.run.steps[2].execution_ids == ()
    assert staged.normalized.steps[2].executions[0].execution_id == (
        staged.normalized.steps[1].executions[0].execution_id
    )
    source_a = next(
        portfolio
        for portfolio in staged.normalized.steps[1].executions[0].portfolios
        if _portfolio_object_id(portfolio) == OBJECT_A
    )
    assert staged.normalized.steps[2].executions[0].portfolios[0] is source_a


def test_empty_filter_skips_downstream_provider_call_without_fabricating_execution():
    _workflow, run = _planned(1.1)
    executor = _FixtureExecutor(allow_downstream=False)

    staged = execute_staged_workflow_run(run, EndpointRegistry(), executor)

    assert [(broker, origin, endpoint) for broker, origin, endpoint, _ in executor.calls] == [
        ("lasair", "ztf", "cone"),
        ("lasair", "ztf", "query"),
        ("fink", "ztf", "objects"),
    ]
    assert _object_ids(staged.normalized.steps[2]) == ()
    assert staged.bindings[3].bound_calls == ()
    assert staged.run.steps[3].state.value == "succeeded"
    assert staged.run.steps[3].execution_ids == ()
    assert staged.normalized.steps[3].executions == ()
