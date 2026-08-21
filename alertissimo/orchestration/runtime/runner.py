"""Synchronous execution control for already planned and bound workflows.

The runtime preserves semantic Step occurrences while allowing an EndpointPlan to
reuse a physical execution already owned by an earlier Step. Reuse is a planner
decision and never collapses WorkflowIR. Required physical plans remain fail-fast;
supplementary plans may fail without failing an otherwise satisfied semantic Step.
"""

from __future__ import annotations

from dataclasses import dataclass

from alertissimo.data_layer.execution.executor import RegistryEndpointExecutor
from alertissimo.data_layer.execution.models import ExecutionResult
from alertissimo.orchestration.binding.models import (
    BoundEndpointCall,
    StepBindingResult,
)
from alertissimo.orchestration.ir.models import DeriveStep, MatchStep

from .models import EndpointPlan, StepRun, StepRunState, WorkflowRun


@dataclass(frozen=True)
class StepExecutionResult:
    """Physical execution results satisfying one semantic Step occurrence."""

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
    """Delegate one independently owned bound call to the physical executor."""

    plan = call.endpoint_plan
    return executor.execute(
        broker=plan.broker,
        origin=plan.origin,
        endpoint=plan.endpoint,
        params=call.params,
    )


def _plan_identity(plan: EndpointPlan) -> tuple[str, str, str]:
    return plan.broker, plan.origin, plan.endpoint


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
            reference = owned_plan.execution_reuse_from
            if reference is None:
                continue
            if reference.step_index >= step_run.step_index:
                raise WorkflowExecutionAlignmentError(
                    "execution reuse must reference an earlier Step occurrence"
                )
            owner_step = run.steps[reference.step_index]
            if reference.plan_index >= len(owner_step.endpoint_plans):
                raise WorkflowExecutionAlignmentError(
                    "execution reuse references an unavailable endpoint plan"
                )
            owner_plan = owner_step.endpoint_plans[reference.plan_index]
            if _plan_identity(owner_plan) != _plan_identity(owned_plan):
                raise WorkflowExecutionAlignmentError(
                    "execution reuse requires identical physical endpoint identity"
                )
            if call.params:
                raise WorkflowExecutionAlignmentError(
                    "reused endpoint plan must not own independent invocation params"
                )


def _updated_run(run: WorkflowRun, step: StepRun) -> WorkflowRun:
    steps = list(run.steps)
    steps[step.step_index] = step
    return run.model_copy(update={"steps": tuple(steps)})


def _error_description(error: Exception) -> str:
    detail = str(error).strip()
    return f"{type(error).__name__}: {detail}" if detail else type(error).__name__


def _supplementary_warning(
    *, step_index: int, plan_index: int, plan: EndpointPlan, error: Exception
) -> str:
    return (
        f"supplementary endpoint plan failed (step_index {step_index}, "
        f"plan_index {plan_index}, {plan.broker}/{plan.origin}/{plan.endpoint}): "
        f"{_error_description(error)}"
    )


def execute_workflow_run(
    run: WorkflowRun,
    bindings: tuple[StepBindingResult, ...],
    executor: RegistryEndpointExecutor,
) -> WorkflowExecutionResult:
    """Execute independent calls once and reuse proven earlier executions.

    A failure of a required EndpointPlan remains fail-fast. A failure of a plan
    marked ``required=False`` is retained as a StepRun warning and execution
    continues. Successful results record the endpoint-plan indexes that produced
    them so later normalization never has to guess across a sparse plan/result set.

    Post-normalization semantic operations such as DeriveStep and MatchStep own no
    physical call. They remain planned here and are completed by the local semantic
    phase after normalized Portfolio data exists.
    """

    _validate_alignment(run, bindings)
    updated_run = run
    step_results: list[StepExecutionResult] = []
    execution_cache: dict[tuple[int, int], ExecutionResult] = {}

    for step_run, binding in zip(run.steps, bindings):
        step = run.step_at(step_run.step_index)
        if isinstance(step, (DeriveStep, MatchStep)):
            step_results.append(
                StepExecutionResult(step_index=step_run.step_index, executions=())
            )
            continue

        executions: list[ExecutionResult] = []
        execution_plan_indexes: list[int] = []
        warnings: list[str] = []

        for plan_index, call in enumerate(binding.bound_calls):
            plan = call.endpoint_plan
            try:
                reference = plan.execution_reuse_from
                if reference is None:
                    execution = execute_bound_call(call, executor)
                else:
                    cache_key = (reference.step_index, reference.plan_index)
                    try:
                        execution = execution_cache[cache_key]
                    except KeyError as error:
                        raise WorkflowExecutionAlignmentError(
                            "reused execution is not available from its declared owner "
                            f"{cache_key}"
                        ) from error
            except Exception as error:
                if not plan.required:
                    warnings.append(
                        _supplementary_warning(
                            step_index=step_run.step_index,
                            plan_index=plan_index,
                            plan=plan,
                            error=error,
                        )
                    )
                    continue

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
                        "execution_plan_indexes": tuple(execution_plan_indexes),
                        "warnings": tuple(warnings),
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

            executions.append(execution)
            execution_plan_indexes.append(plan_index)
            execution_cache[(step_run.step_index, plan_index)] = execution

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
                "execution_plan_indexes": tuple(execution_plan_indexes),
                "warnings": tuple(warnings),
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
