"""MatchStep is a filtering candidate owner for later targetless retrievals."""

from itertools import count

from alertissimo.data_layer.execution import EndpointRegistry, ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
)
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import compile_surface_to_ir, parse_surface_script
from alertissimo.orchestration.local_semantics import finalize_local_semantics
from alertissimo.orchestration.pipeline import execute_staged_workflow_run
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import StepRunState


DSL = """objects from ztf via alerce
inside (10, 20, 5arcsec)
match on position inside 1arcsec
with lightcurve via fink
"""


class _MatchThenLightcurveExecutor:
    def __init__(self, *, matched: bool = True):
        self.matched = matched
        self.calls: list[tuple[str, str, str, dict]] = []
        self._ids = count(1)

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        del headers
        params = dict(params or {})
        self.calls.append((broker, origin, endpoint, params))

        if (broker, origin, endpoint) == ("alerce", "ztf", "query_objects"):
            second_ra = 10.0001 if self.matched else 10.001
            payload = {
                "items": [
                    {
                        "oid": "ZTF20matcha",
                        "meanra": 10.0,
                        "meandec": 20.0,
                    },
                    {
                        "oid": "ZTF20matchb",
                        "meanra": second_ra,
                        "meandec": 20.0,
                    },
                    {
                        "oid": "ZTF20unmatched",
                        "meanra": 10.002,
                        "meandec": 20.0,
                    },
                ]
            }
        elif (broker, origin, endpoint) == ("fink", "ztf", "objects"):
            assert self.matched
            assert params["objectId"] == "ZTF20matcha,ZTF20matchb"
            payload = []
        else:  # pragma: no cover - planner contract fixes the calls above.
            raise AssertionError(f"unexpected endpoint {(broker, origin, endpoint)!r}")

        return ExecutionResult(
            payload=payload,
            execution_provenance=InternalExecutionProvenance(
                internal_execution_id=InternalExecutionId(
                    f"execution:match-downstream:{next(self._ids)}"
                ),
                broker=broker,
                origin=origin,
                endpoint=endpoint,
                params=params,
            ),
        )


def _planned_workflow():
    graph = build_capability_graph()
    workflow = compile_surface_to_ir(
        parse_surface_script(DSL),
        graph=graph,
        name="MatchStep downstream candidate propagation",
    )
    return workflow, plan_workflow(workflow, graph)


def test_downstream_get_binds_only_match_survivors():
    workflow, run = _planned_workflow()
    assert [step.op for step in workflow.steps] == [
        "cone_search",
        "match",
        "get_lightcurve",
    ]

    match_run = run.steps[1]
    get_run = run.steps[2]
    assert match_run.candidate_input_from is not None
    assert match_run.candidate_input_from.step_index == 0
    assert len(get_run.endpoint_plans) == 1
    assert get_run.endpoint_plans[0].candidate_input_from is not None
    assert get_run.endpoint_plans[0].candidate_input_from.step_index == 1

    executor = _MatchThenLightcurveExecutor(matched=True)
    staged = execute_staged_workflow_run(
        run,
        EndpointRegistry(),
        executor,
        validate_semantic_model=True,
    )

    assert [(broker, origin, endpoint) for broker, origin, endpoint, _ in executor.calls] == [
        ("alerce", "ztf", "query_objects"),
        ("fink", "ztf", "objects"),
    ]
    assert staged.bindings[2].bound_calls[0].params["objectId"] == (
        "ZTF20matcha,ZTF20matchb"
    )
    assert staged.run.steps[0].state is StepRunState.SUCCEEDED
    assert staged.run.steps[1].state is StepRunState.PLANNED
    assert staged.run.steps[2].state is StepRunState.SUCCEEDED

    finalized = finalize_local_semantics(staged.normalized)
    assert len(finalized.steps[0].portfolios) == 3
    assert len(finalized.steps[1].portfolios) == 2
    matched_ids = {
        str(record.fields["identity.object_id"])
        for portfolio in finalized.steps[1].portfolios
        for record in portfolio.records
        if record.semantic_type.startswith("summary@")
    }
    assert matched_ids == {"ZTF20matcha", "ZTF20matchb"}


def test_empty_match_makes_downstream_get_vacuous():
    _, run = _planned_workflow()
    executor = _MatchThenLightcurveExecutor(matched=False)

    staged = execute_staged_workflow_run(
        run,
        EndpointRegistry(),
        executor,
        validate_semantic_model=True,
    )

    assert [(broker, origin, endpoint) for broker, origin, endpoint, _ in executor.calls] == [
        ("alerce", "ztf", "query_objects")
    ]
    assert staged.bindings[2].bound_calls == ()
    assert staged.run.steps[1].state is StepRunState.PLANNED
    assert staged.run.steps[2].state is StepRunState.SUCCEEDED
    assert staged.run.steps[2].vacuous_plan_indexes == (0,)

    finalized = finalize_local_semantics(staged.normalized)
    assert finalized.steps[1].portfolios == ()
