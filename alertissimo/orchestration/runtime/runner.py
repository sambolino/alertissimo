"""Synchronous execution control for already planned and bound workflows.

The orchestration runtime drives Step occurrence lifecycle while delegating each
physical call to ``RegistryEndpointExecutor``.  ``WorkflowRun`` retains only
lifecycle facts and execution IDs; raw payload and complete call provenance stay
in the transient ``ExecutionResult`` values returned here for a later semantic
normalization and Portfolio-composition layer.  DeriveStep occurrences deliberately
remain planned here: they own no physical call and run only after normalization.
"""

from __future__ import annotations

from dataclasses import dataclass

from alertissimo.data_layer.execution.executor import RegistryEndpointExecutor
from alertissimo.data_layer.execution.models import ExecutionResult
from alertissimo.orchestration.binding.models import (
    BoundEndpointCall,
    StepBindingResult,
)
from alertissimo.orchestration.ir.models import DeriveStep

from .models import StepRun, StepRunState, WorkflowRun


@dataclass(frozen=True)
class StepExecutionResult:
    """Successful physical executions belonging to one Step occurrence."""

    step_index: int
    executions: tuple[ExecutionResult, ...]


@dataclass(frozen=True)
class WorkflowExecutionResult:
    """Updated workflow lifecycle state and its transient physical results."""

    run: WorkflowRun
    steps: tuple[StepExecutionResult, ...]


class WorkflowExecutionAlignmentError(ValueError):
    """Raised before execution when a planned run and bindings do not align."""


class WorkflowExecutionError(RuntimeError):
    """Fail-fast execution error retaining updated state and partial results."""

    def __init__(
        self,
        message: str,
        *,
        workflow_run: WorkflowRun,
        completed_steps: tuple[StepExecutionResult, ...],
    ) -> None:
        super().__init__(message)
        self.workflow_run = workflow_run
        self.completed_steps = completed_steps


def execute_bound_call(
    call: BoundEndpointCall, executor: RegistryEndpointExecutor
) -> ExecutionResult:
    """Delegate one bound call to the physical endpoint executor."""

    plan = call.endpoint_plan
    return executor.execute(
        broker=plan.broker,
        origin=plan.origin,
        endpoint=plan.endpoint,
        params=call.params,
    )


def _validate_alignment(
    run: WorkflowRun, bindings: tuple[StepBindingResult, ...]
) -> None:
    if len(bindings) != len(run.steps):
        raise WorkflowExecutionAlignmentError(
            "binding count does not match WorkflowRun StepRun count "
            f"({len(bindings)} != {len(run.steps)})"
        )

    for position, (step_run, binding) in enumerate(zip(run.steps, bindings)):
        if step_run.state is not StepRunState.PLANNED:
            raise WorkflowExecutionAlignmentError(
                f"step_index {step_run.step_index} is {step_run.state.value}; "
                "execution requires planned state"
            )
        if binding.step_index != step_run.step_index:
            raise WorkflowExecutionAlignmentError(
                f"binding at position {position} has step_index {binding.step_index}; "
                f"expected {step_run.step_index}"
            )
        if len(binding.bound_calls) != len(step_run.endpoint_plans):
            raise WorkflowExecutionAlignmentError(
                f"step_index {step_run.step_index} bound call count does not match "
                "endpoint plan count "
                f"({len(binding.bound_calls)} != {len(step_run.endpoint_plans)})"
            )
        for call_position, (call, owned_plan) in enumerate(
            zip(binding.bound_calls, step_run.endpoint_plans)
        ):
            if call.endpoint_plan != owned_plan:
                raise WorkflowExecutionAlignmentError(
                    f"step_index {step_run.step_index} bound call {call_position} "
                    "does not match its owned EndpointPlan"
                )


def _updated_run(run: WorkflowRun, step: StepRun) -> WorkflowRun:
    steps = list(run.steps)
    steps[step.step_index] = step
    return run.model_copy(update={"steps": tuple(steps)})


def _error_description(error: Exception) -> str:
    detail = str(error).strip()
    return f"{type(error).__name__}: {detail}" if detail else type(error).__name__


def execute_workflow_run(
    run: WorkflowRun,
    bindings: tuple[StepBindingResult, ...],
    executor: RegistryEndpointExecutor,
) -> WorkflowExecutionResult:
    """Execute physical calls sequentially; leave DeriveSteps for Portfolio phase."""

    _validate_alignment(run, bindings)
    updated_run = run
    step_results: list[StepExecutionResult] = []

    for step_run, binding in zip(run.steps, bindings):
        step = run.step_at(step_run.step_index)
        if isinstance(step, DeriveStep):
            step_results.append(
                StepExecutionResult(step_index=step_run.step_index, executions=())
            )
            continue

        executions: list[ExecutionResult] = []
        try:
            for call in binding.bound_calls:
                executions.append(execute_bound_call(call, executor))
        except Exception as error:
            partial_result = StepExecutionResult(
                step_index=step_run.step_index, executions=tuple(executions)
            )
            step_results.append(partial_result)
            failed_step = step_run.model_copy(
                update={
                    "state": StepRunState.FAILED,
                    "execution_ids": tuple(
                        item.internal_execution_id.value for item in executions
                    ),
                    "error": _error_description(error),
                }
            )
            updated_run = _updated_run(updated_run, failed_step)
            raise WorkflowExecutionError(
                f"step_index {step_run.step_index} execution failed: "
                f"{_error_description(error)}",
                workflow_run=updated_run,
                completed_steps=tuple(step_results),
            ) from error

        step_results.append(
            StepExecutionResult(
                step_index=step_run.step_index, executions=tuple(executions)
            )
        )
        succeeded_step = step_run.model_copy(
            update={
                "state": StepRunState.SUCCEEDED,
                "execution_ids": tuple(
                    item.internal_execution_id.value for item in executions
                ),
                "error": None,
            }
        )
        updated_run = _updated_run(updated_run, succeeded_step)

    return WorkflowExecutionResult(run=updated_run, steps=tuple(step_results))


__all__ = [
    "StepExecutionResult",
    "WorkflowExecutionAlignmentError",
    "WorkflowExecutionError",
    "WorkflowExecutionResult",
    "execute_bound_call",
    "execute_workflow_run",
]
