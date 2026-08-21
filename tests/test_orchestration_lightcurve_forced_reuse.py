"""Execution-reuse contracts for automatic lightcurve forced-photometry evidence."""

from alertissimo.data_layer.execution import EndpointRegistry
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.orchestration.binding import bind_workflow_run
from alertissimo.orchestration.ir import (
    GetForcedPhotometryStep,
    GetLightcurveStep,
    Source,
    TargetSelector,
    WorkflowIR,
)
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import EndpointPlanRef, execute_workflow_run
from scripts.smoke.executors import FixtureEndpointExecutor, fixture_key


OBJECT_ID = "ZTF18abbuksn"


def _workflow(forced_target: str = OBJECT_ID) -> WorkflowIR:
    return WorkflowIR(
        steps=[
            GetForcedPhotometryStep(
                target=TargetSelector(ids=[forced_target], kind="object"),
                sources=[Source(broker="alerce", origin="ztf")],
            ),
            GetLightcurveStep(
                target=TargetSelector(ids=[OBJECT_ID], kind="object"),
                sources=[Source(broker="alerce", origin="ztf")],
            ),
        ]
    )


def test_lightcurve_supplement_reuses_equivalent_explicit_forced_step():
    run = plan_workflow(_workflow(), build_capability_graph())

    assert [plan.endpoint for plan in run.steps[0].endpoint_plans] == [
        "query_forced_photometry"
    ]
    assert [plan.endpoint for plan in run.steps[1].endpoint_plans] == [
        "query_lightcurve",
        "query_forced_photometry",
    ]
    assert run.steps[1].endpoint_plans[1].execution_reuse_from == EndpointPlanRef(
        step_index=0,
        plan_index=0,
    )
    assert run.steps[1].endpoint_plans[1].candidate_input_from is None

    bindings = bind_workflow_run(run, EndpointRegistry())
    assert [call.params for call in bindings[0].bound_calls] == [{"oid": OBJECT_ID}]
    assert [call.params for call in bindings[1].bound_calls] == [
        {"oid": OBJECT_ID},
        {},
    ]


def test_equivalent_forced_supplement_executes_only_once_and_reuses_execution_id():
    graph = build_capability_graph()
    run = plan_workflow(_workflow(), graph)
    registry = EndpointRegistry()
    bindings = bind_workflow_run(run, registry)
    executor = FixtureEndpointExecutor(
        {
            fixture_key(
                "alerce", "ztf", "query_forced_photometry", oid=OBJECT_ID
            ): "../../../tests/fixtures/alerce/ztf/query_forced_photometry.json",
            fixture_key(
                "alerce", "ztf", "query_lightcurve", oid=OBJECT_ID
            ): "../../../tests/fixtures/alerce/ztf/query_lightcurve.json",
        }
    )

    executed = execute_workflow_run(run, bindings, executor)

    assert [(broker, origin, endpoint) for broker, origin, endpoint, _ in executor.calls] == [
        ("alerce", "ztf", "query_forced_photometry"),
        ("alerce", "ztf", "query_lightcurve"),
    ]
    forced_execution_id = executed.run.steps[0].execution_ids[0]
    assert executed.run.steps[1].execution_ids == (
        "execution:smoke:2",
        forced_execution_id,
    )
    assert (
        executed.steps[1].executions[1]
        is executed.steps[0].executions[0]
    )


def test_different_explicit_target_is_not_reused():
    run = plan_workflow(_workflow(forced_target="ZTF20different"), build_capability_graph())

    assert run.steps[1].endpoint_plans[1].execution_reuse_from is None
