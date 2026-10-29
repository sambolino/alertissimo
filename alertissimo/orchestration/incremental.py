"""Resume an extended workflow without repeating prior physical provider calls.

Incremental execution is intentionally input-interface agnostic. A DSL, visual,
NLP, or programmatic client may extend a previously executed canonical workflow,
plan the extended WorkflowIR normally, and pass the resulting WorkflowRun here.
The previous physical executions are replayed from the prior staged result while
only newly appended work reaches the underlying endpoint executor.

The extended workflow must preserve the previous workflow as an exact semantic and
physical-plan prefix. If appending new intent would retroactively change an older
Step or its plan, continuation is refused rather than silently re-running providers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from alertissimo.data_layer.execution import EndpointRegistry, ExecutionResult
from alertissimo.orchestration.pipeline import (
    EndpointExecutor,
    StagedWorkflowResult,
    execute_staged_workflow_run,
)
from alertissimo.orchestration.runtime import StepExecutionResult, StepRun, WorkflowRun


class IncrementalExecutionError(ValueError):
    """An extended workflow cannot safely reuse the previous execution prefix."""


def _execution_plan_indexes(
    step_run: StepRun,
    step_result: StepExecutionResult,
) -> tuple[int, ...]:
    if step_run.execution_plan_indexes:
        if len(step_run.execution_plan_indexes) != len(step_result.executions):
            raise IncrementalExecutionError(
                f"previous step_index {step_run.step_index} has execution-plan "
                "metadata that does not align with its executions"
            )
        return step_run.execution_plan_indexes
    if len(step_run.endpoint_plans) == len(step_result.executions):
        return tuple(range(len(step_result.executions)))
    if not step_result.executions:
        return ()
    raise IncrementalExecutionError(
        f"previous step_index {step_run.step_index} has sparse executions without "
        "execution-plan index metadata"
    )


@dataclass(frozen=True)
class _ReplayCall:
    broker: str
    origin: str
    endpoint: str
    params: dict[str, Any]
    execution: ExecutionResult


def _physical_calls(previous: StagedWorkflowResult) -> tuple[_ReplayCall, ...]:
    """Return real prior invocations with their pre-executor bound parameters.

    Execution provenance contains executor-expanded defaults/fixed parameters, while
    an incremental replay arrives at the same boundary as the original bound call.
    The previous ``StepBindingResult`` is therefore the authoritative comparison
    point. Semantic execution reuse is deliberately skipped because it never caused
    another physical invocation in the previous run.
    """

    physical: list[_ReplayCall] = []
    if not (len(previous.run.steps) == len(previous.bindings) == len(previous.execution.steps)):
        raise IncrementalExecutionError("previous Steps, bindings, and results do not align")
    for step_run, binding, step_result in zip(
        previous.run.steps,
        previous.bindings,
        previous.execution.steps,
    ):
        if step_result.step_index != step_run.step_index:
            raise IncrementalExecutionError("previous Step result is not occurrence-aligned")
        plan_indexes = _execution_plan_indexes(step_run, step_result)
        if any(index < 0 or index >= len(step_run.endpoint_plans) for index in plan_indexes):
            raise IncrementalExecutionError("previous execution references an unavailable endpoint plan")
        successful: dict[int, list[ExecutionResult]] = {}
        for index, execution in zip(plan_indexes, step_result.executions):
            successful.setdefault(index, []).append(execution)
        pending = {index: iter(executions) for index, executions in successful.items()}
        if binding.plan_indexes:
            bound_indexes = binding.plan_indexes
        elif len(binding.bound_calls) == len(step_run.endpoint_plans):
            bound_indexes = tuple(range(len(step_run.endpoint_plans)))
        elif not binding.bound_calls:
            bound_indexes = ()
        else:
            raise IncrementalExecutionError("previous fan-out bindings require plan index metadata")
        if binding.step_index != step_run.step_index or len(bound_indexes) != len(binding.bound_calls):
            raise IncrementalExecutionError("previous binding does not align with its Step and calls")
        covered = set()
        for plan_index, call in zip(bound_indexes, binding.bound_calls):
            if plan_index < 0 or plan_index >= len(step_run.endpoint_plans):
                raise IncrementalExecutionError("previous binding references an unavailable endpoint plan")
            if plan_index in step_run.vacuous_plan_indexes:
                raise IncrementalExecutionError("previous vacuous plan unexpectedly has bound calls")
            plan = step_run.endpoint_plans[plan_index]
            covered.add(plan_index)
            if call.endpoint_plan != plan:
                raise IncrementalExecutionError(
                    f"previous step_index {step_run.step_index} binding is not "
                    f"aligned at plan_index {plan_index}"
                )
            if plan.execution_reuse_from is not None:
                continue  # One binding can stand for an entire reused execution group.
            try:
                execution = next(pending.get(plan_index, iter(())))
            except StopIteration as error:
                raise IncrementalExecutionError(
                    "previous physical call has no aligned successful execution at "
                    f"step_index {step_run.step_index}, plan_index {plan_index}"
                ) from error
            physical.append(_ReplayCall(
                broker=plan.broker, origin=plan.origin, endpoint=plan.endpoint,
                params=dict(call.params), execution=execution,
            ))
        expected = set(range(len(step_run.endpoint_plans))) - set(step_run.vacuous_plan_indexes)
        if covered != expected:
            raise IncrementalExecutionError(
                f"previous step_index {step_run.step_index} binding does not cover its non-vacuous endpoint plans"
            )
        for plan_index, remaining in pending.items():
            if step_run.endpoint_plans[plan_index].execution_reuse_from is not None:
                continue
            if next(remaining, None) is not None:
                raise IncrementalExecutionError(
                    f"previous step_index {step_run.step_index} has extra successful executions at plan_index {plan_index}"
                )

    return tuple(physical)


def _planning_signature(step_run: StepRun):
    return (
        step_run.endpoint_plans,
        step_run.candidate_input_from,
        step_run.material_input_from,
    )


def _require_extension_prefix(
    previous: StagedWorkflowResult,
    extended_run: WorkflowRun,
) -> None:
    previous_run = previous.run
    previous_count = len(previous_run.workflow.steps)
    if len(extended_run.workflow.steps) < previous_count:
        raise IncrementalExecutionError(
            "incremental workflow removed previously executed semantic Steps"
        )

    previous_steps = tuple(previous_run.workflow.steps)
    extended_prefix = tuple(extended_run.workflow.steps[:previous_count])
    if extended_prefix != previous_steps:
        raise IncrementalExecutionError(
            "new intent changes the previously executed semantic workflow prefix; "
            "start a fresh execution instead of continuing this result"
        )

    for index, (previous_step_run, extended_step_run) in enumerate(
        zip(previous_run.steps, extended_run.steps[:previous_count])
    ):
        if _planning_signature(previous_step_run) != _planning_signature(extended_step_run):
            raise IncrementalExecutionError(
                "new intent changes the previously executed physical plan at "
                f"step_index {index}; start a fresh execution instead"
            )
        if any(plan.time_selection is not None for plan in previous_step_run.endpoint_plans):
            binding = next((item for item in previous.bindings if item.step_index == index), None)
            if binding is None or binding.reference_time != previous_step_run.time_reference:
                raise IncrementalExecutionError(
                    f"previous temporal reference is inconsistent at step_index {index}"
                )
        if previous_step_run.warnings:
            raise IncrementalExecutionError(
                "cannot safely continue a prior Step with incomplete supplementary "
                f"execution at step_index {index}; start a fresh execution instead"
            )


def _call_description(
    broker: str,
    origin: str,
    endpoint: str,
    params,
) -> str:
    return f"{broker}/{origin}/{endpoint} params={dict(params or {})!r}"


@dataclass
class _PrefixReplayExecutor:
    """Replay the previous physical-call prefix, then delegate genuinely new work."""

    previous_calls: tuple[_ReplayCall, ...]
    delegate: EndpointExecutor
    replayed: int = 0

    def execute(self, broker: str, origin: str, endpoint: str, params=None, headers=None):
        if self.replayed < len(self.previous_calls):
            previous = self.previous_calls[self.replayed]
            expected_identity = previous.broker, previous.origin, previous.endpoint
            actual_identity = broker, origin, endpoint
            expected_params = previous.params
            actual_params = dict(params or {})
            if expected_identity != actual_identity or expected_params != actual_params:
                raise IncrementalExecutionError(
                    "extended workflow no longer reproduces the previous physical-call "
                    f"prefix at call {self.replayed + 1}: expected "
                    f"{_call_description(*expected_identity, expected_params)}, got "
                    f"{_call_description(*actual_identity, actual_params)}"
                )
            self.replayed += 1
            return previous.execution

        return self.delegate.execute(
            broker=broker,
            origin=origin,
            endpoint=endpoint,
            params=params,
            headers=headers,
        )

    def require_complete_replay(self) -> None:
        if self.replayed != len(self.previous_calls):
            raise IncrementalExecutionError(
                "extended workflow did not consume the complete previous physical-call "
                f"prefix ({self.replayed}/{len(self.previous_calls)} replayed)"
            )


def execute_incremental_workflow_run(
    run: WorkflowRun,
    previous: StagedWorkflowResult,
    registry: EndpointRegistry,
    executor: EndpointExecutor,
    *,
    validate_semantic_model: bool = True,
    reference_time: datetime | None = None,
) -> StagedWorkflowResult:
    """Execute an extended planned workflow while replaying its prior call prefix.

    Planning and normalization intentionally run again over the cumulative workflow
    so the returned result is a complete immutable semantic snapshot. Physical
    provider calls from ``previous`` are not repeated; after the exact old prefix
    has been replayed, only newly appended work is delegated to ``executor``.
    """

    _require_extension_prefix(previous, run)
    replay = _PrefixReplayExecutor(_physical_calls(previous), executor)
    staged = execute_staged_workflow_run(
        run,
        registry,
        replay,
        validate_semantic_model=validate_semantic_model,
        reference_time=reference_time,
        _reference_times={
            binding.step_index: binding.reference_time
            for binding in previous.bindings if binding.reference_time is not None
        },
    )
    replay.require_complete_replay()
    return staged


__all__ = [
    "IncrementalExecutionError",
    "execute_incremental_workflow_run",
]
