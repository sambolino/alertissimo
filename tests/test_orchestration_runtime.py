"""Focused tests for minimal workflow invocation state."""

from alertissimo.orchestration.ir import TargetSelector
import pytest
from pydantic import ValidationError

from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.orchestration.ir.models import (
    GetLightcurveStep,
    Source,
    WorkflowIR,
)
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import StepRun, StepRunState, WorkflowRun


def _repeated_workflow() -> WorkflowIR:
    source = [Source(broker="lasair", origin="ztf")]
    return WorkflowIR(
        steps=[
            GetLightcurveStep(target=TargetSelector(ids=["A"], kind="object"), sources=source),
            GetLightcurveStep(target=TargetSelector(ids=["B"], kind="object"), sources=source),
        ]
    )


def test_from_workflow_creates_ordered_pending_step_runs():
    workflow = _repeated_workflow()
    run = WorkflowRun.from_workflow(workflow)

    assert [step.step_index for step in run.steps] == [0, 1]
    assert all(step.state is StepRunState.PENDING for step in run.steps)
    assert all(step.endpoint_plans == () for step in run.steps)
    assert run.step_at(1).target.ids == ["B"]
    assert run.step_run_at(0) is run.steps[0]


@pytest.mark.parametrize(
    "steps",
    [
        (StepRun(step_index=0),),
        (StepRun(step_index=0), StepRun(step_index=0)),
        (StepRun(step_index=1), StepRun(step_index=0)),
    ],
)
def test_workflow_run_rejects_missing_duplicate_or_out_of_order_indices(steps):
    with pytest.raises(ValidationError, match="indices must cover"):
        WorkflowRun(workflow=_repeated_workflow(), steps=steps)


def test_step_run_rejects_negative_index():
    with pytest.raises(ValidationError):
        StepRun(step_index=-1)


def test_same_operation_steps_remain_distinct_after_planning():
    run = plan_workflow(_repeated_workflow(), build_capability_graph())

    assert [step.step_index for step in run.steps] == [0, 1]
    assert [run.step_at(step.step_index).target.ids[0] for step in run.steps] == ["A", "B"]
    assert all(step.state is StepRunState.PLANNED for step in run.steps)
    assert [step.endpoint_plans[0].endpoint for step in run.steps] == [
        "lightcurves",
        "lightcurves",
    ]
    assert run.steps[0].endpoint_plans is not run.steps[1].endpoint_plans
    assert all(
        not hasattr(plan, "target_id") and not hasattr(plan, "step_op")
        for step in run.steps
        for plan in step.endpoint_plans
    )


def test_workflow_run_json_round_trip_preserves_discriminated_steps():
    run = plan_workflow(_repeated_workflow(), build_capability_graph())

    restored = WorkflowRun.model_validate_json(run.model_dump_json())

    assert restored == run
    assert isinstance(restored.workflow.steps[0], GetLightcurveStep)
