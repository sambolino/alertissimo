"""Offline tests for synchronous orchestration runtime execution."""

from __future__ import annotations

from alertissimo.orchestration.ir import TargetSelector

from dataclasses import replace

import pytest

from alertissimo.data_layer.execution import EndpointRegistry, ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
)
from alertissimo.orchestration.binding import bind_workflow_run
from alertissimo.orchestration.binding.models import StepBindingResult
from alertissimo.orchestration.ir import GetLightcurveStep, WorkflowIR
from alertissimo.orchestration.runtime import (
    EndpointPlan,
    StepRun,
    StepRunState,
    WorkflowExecutionAlignmentError,
    WorkflowExecutionError,
    WorkflowRun,
    execute_bound_call,
    execute_workflow_run,
)


class FakeExecutor:
    def __init__(self, *, fail_at: int | None = None) -> None:
        self.calls: list[tuple[str, str, str, dict[str, object]]] = []
        self.fail_at = fail_at

    def execute(self, *, broker, origin, endpoint, params):
        call = (broker, origin, endpoint, dict(params))
        self.calls.append(call)
        if self.fail_at == len(self.calls):
            raise ConnectionError("provider unavailable")
        execution_id = InternalExecutionId(f"execution:{len(self.calls)}")
        return ExecutionResult(
            payload={"call": len(self.calls)},
            execution_provenance=InternalExecutionProvenance(
                internal_execution_id=execution_id,
                broker=broker,
                origin=origin,
                endpoint=endpoint,
                params=params,
            ),
        )


def _plan(broker: str, origin: str, endpoint: str) -> EndpointPlan:
    return EndpointPlan(broker=broker, origin=origin, endpoint=endpoint)


def _planned_run(
    targets: tuple[str, ...], plans: tuple[tuple[EndpointPlan, ...], ...]
) -> WorkflowRun:
    workflow = WorkflowIR(
        steps=tuple(GetLightcurveStep(target=TargetSelector(ids=[target], kind="object")) for target in targets)
    )
    return WorkflowRun(
        workflow=workflow,
        steps=tuple(
            StepRun(
                step_index=index,
                state=StepRunState.PLANNED,
                endpoint_plans=step_plans,
            )
            for index, step_plans in enumerate(plans)
        ),
    )


def test_execute_bound_call_delegates_plan_identity_and_bound_params():
    run = _planned_run(
        ("ZTF20abc",), ((_plan("lasair", "ztf", "lightcurves"),),)
    )
    call = bind_workflow_run(run, EndpointRegistry())[0].bound_calls[0]
    executor = FakeExecutor()

    result = execute_bound_call(call, executor)

    assert result.internal_execution_id.value == "execution:1"
    assert executor.calls == [
        ("lasair", "ztf", "lightcurves", {"objectIds": "ZTF20abc"})
    ]


def test_success_updates_new_run_and_retains_raw_execution():
    run = _planned_run(("A",), ((_plan("lasair", "ztf", "lightcurves"),),))
    bindings = bind_workflow_run(run, EndpointRegistry())

    result = execute_workflow_run(run, bindings, FakeExecutor())

    assert run.steps[0].state is StepRunState.PLANNED
    assert run.steps[0].execution_ids == ()
    assert result.run.steps[0].state is StepRunState.SUCCEEDED
    assert result.run.steps[0].execution_ids == ("execution:1",)
    assert result.run.steps[0].error is None
    assert result.steps[0].step_index == 0
    assert result.steps[0].executions[0].payload == {"call": 1}
    assert WorkflowRun.model_validate_json(result.run.model_dump_json()) == result.run


def test_repeated_occurrences_and_endpoint_fanout_execute_in_stable_order():
    lasair = _plan("lasair", "ztf", "lightcurves")
    alerce = _plan("alerce", "lsst", "query_lightcurve")
    run = _planned_run(
        ("170587117485817955", "B"), ((alerce, lasair), (lasair,))
    )
    bindings = bind_workflow_run(run, EndpointRegistry())
    executor = FakeExecutor()

    result = execute_workflow_run(run, bindings, executor)

    assert [step.step_index for step in result.steps] == [0, 1]
    assert [len(step.executions) for step in result.steps] == [2, 1]
    assert result.run.steps[0].execution_ids == ("execution:1", "execution:2")
    assert result.run.steps[1].execution_ids == ("execution:3",)
    assert executor.calls == [
        (
            "alerce",
            "lsst",
            "query_lightcurve",
            {"oid": 170587117485817955},
        ),
        (
            "lasair",
            "ztf",
            "lightcurves",
            {"objectIds": "170587117485817955"},
        ),
        ("lasair", "ztf", "lightcurves", {"objectIds": "B"}),
    ]
    assert isinstance(executor.calls[0][3]["oid"], int)
    assert isinstance(executor.calls[1][3]["objectIds"], str)


def test_pending_run_is_rejected_before_execution():
    run = WorkflowRun.from_workflow(
        WorkflowIR(steps=[GetLightcurveStep(target=TargetSelector(ids=["A"], kind="object"))])
    )
    executor = FakeExecutor()

    with pytest.raises(WorkflowExecutionAlignmentError, match="requires planned"):
        execute_workflow_run(
            run, (StepBindingResult(step_index=0, bound_calls=()),), executor
        )

    assert executor.calls == []


@pytest.mark.parametrize("mismatch", ["missing", "index", "count", "plan"])
def test_binding_alignment_mismatch_is_rejected_before_any_call(mismatch):
    first = _plan("lasair", "ztf", "lightcurves")
    second = _plan("alerce", "lsst", "query_lightcurve")
    run = _planned_run(("A",), ((first,),))
    bindings = bind_workflow_run(run, EndpointRegistry())
    binding = bindings[0]
    if mismatch == "missing":
        invalid = ()
    elif mismatch == "index":
        invalid = (replace(binding, step_index=8),)
    elif mismatch == "count":
        invalid = (replace(binding, bound_calls=()),)
    else:
        invalid_call = replace(binding.bound_calls[0], endpoint_plan=second)
        invalid = (replace(binding, bound_calls=(invalid_call,)),)
    executor = FakeExecutor()

    with pytest.raises(WorkflowExecutionAlignmentError):
        execute_workflow_run(run, invalid, executor)

    assert executor.calls == []


def test_failure_preserves_completed_and_partial_results_and_chains_cause():
    lasair = _plan("lasair", "ztf", "lightcurves")
    alerce = _plan("alerce", "lsst", "query_lightcurve")
    run = _planned_run(
        ("1", "2", "3"), ((lasair,), (alerce, lasair), (lasair,))
    )
    bindings = bind_workflow_run(run, EndpointRegistry())

    with pytest.raises(WorkflowExecutionError) as caught:
        execute_workflow_run(run, bindings, FakeExecutor(fail_at=3))

    error = caught.value
    assert isinstance(error.__cause__, ConnectionError)
    assert [step.state for step in error.workflow_run.steps] == [
        StepRunState.SUCCEEDED,
        StepRunState.FAILED,
        StepRunState.PLANNED,
    ]
    assert error.workflow_run.steps[0].execution_ids == ("execution:1",)
    assert error.workflow_run.steps[1].execution_ids == ("execution:2",)
    assert error.workflow_run.steps[1].error == (
        "ConnectionError: provider unavailable"
    )
    assert error.workflow_run.steps[2].execution_ids == ()
    assert [item.step_index for item in error.completed_steps] == [0, 1]
    assert [len(item.executions) for item in error.completed_steps] == [1, 1]
    assert run.steps[0].state is StepRunState.PLANNED
    restored = WorkflowRun.model_validate_json(error.workflow_run.model_dump_json())
    assert restored == error.workflow_run


def test_multi_id_step_remains_one_physical_execution():
    workflow = WorkflowIR(steps=[GetLightcurveStep(target=TargetSelector(ids=["A", "B"], kind="object"))])
    endpoint = _plan("lasair", "ztf", "lightcurves")
    run = WorkflowRun(
        workflow=workflow,
        steps=(StepRun(step_index=0, state=StepRunState.PLANNED, endpoint_plans=(endpoint,)),),
    )
    bindings = bind_workflow_run(run, EndpointRegistry())
    executor = FakeExecutor()

    result = execute_workflow_run(run, bindings, executor)

    assert len(bindings[0].bound_calls) == 1
    assert len(result.steps[0].executions) == 1
    assert executor.calls == [("lasair", "ztf", "lightcurves", {"objectIds": "A,B"})]
