"""Resume an extended workflow without repeating prior physical provider calls.

Incremental execution is intentionally input-interface agnostic.  A DSL, visual,
NLP, or programmatic client may extend a previously executed canonical workflow,
plan the extended WorkflowIR normally, and pass the resulting WorkflowRun here.
The previous physical executions are replayed from the prior staged result while
only newly appended work reaches the underlying endpoint executor.

The extended workflow must preserve the previous workflow as an exact semantic and
physical-plan prefix.  If appending new intent would retroactively change an older
Step or its plan, continuation is refused rather than silently re-running providers.
"""

from __future__ import annotations

from dataclasses import dataclass

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


def _physical_executions(previous: StagedWorkflowResult) -> tuple[ExecutionResult, ...]:
    """Return only executions that represented real provider invocations.

    A later semantic Step may carry an earlier ExecutionResult through
    ``execution_reuse_from``.  That occurrence must not be replayed as another
    provider call during incremental execution.
    """

    physical: list[ExecutionResult] = []
    for step_run, step_result in zip(previous.run.steps, previous.execution.steps):
        for plan_index, execution in zip(
            _execution_plan_indexes(step_run, step_result),
            step_result.executions,
        ):
            plan = step_run.endpoint_plans[plan_index]
            if plan.execution_reuse_from is None:
                physical.append(execution)
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

    previous_executions: tuple[ExecutionResult, ...]
    delegate: EndpointExecutor
    replayed: int = 0

    def execute(self, broker: str, origin: str, endpoint: str, params=None, headers=None):
        if self.replayed < len(self.previous_executions):
            previous = self.previous_executions[self.replayed]
            provenance = previous.execution_provenance
            expected_identity = (
                provenance.broker,
                provenance.origin,
                provenance.endpoint,
            )
            actual_identity = (broker, origin, endpoint)
            expected_params = dict(provenance.params or {})
            actual_params = dict(params or {})
            if expected_identity != actual_identity or expected_params != actual_params:
                raise IncrementalExecutionError(
                    "extended workflow no longer reproduces the previous physical-call "
                    f"prefix at call {self.replayed + 1}: expected "
                    f"{_call_description(*expected_identity, expected_params)}, got "
                    f"{_call_description(*actual_identity, actual_params)}"
                )
            self.replayed += 1
            return previous

        return self.delegate.execute(
            broker=broker,
            origin=origin,
            endpoint=endpoint,
            params=params,
            headers=headers,
        )

    def require_complete_replay(self) -> None:
        if self.replayed != len(self.previous_executions):
            raise IncrementalExecutionError(
                "extended workflow did not consume the complete previous physical-call "
                f"prefix ({self.replayed}/{len(self.previous_executions)} replayed)"
            )


def execute_incremental_workflow_run(
    run: WorkflowRun,
    previous: StagedWorkflowResult,
    registry: EndpointRegistry,
    executor: EndpointExecutor,
    *,
    validate_semantic_model: bool = True,
) -> StagedWorkflowResult:
    """Execute an extended planned workflow while replaying its prior call prefix.

    Planning and normalization intentionally run again over the cumulative workflow
    so the returned result is a complete immutable semantic snapshot.  Physical
    provider calls from ``previous`` are not repeated; after the exact old prefix
    has been replayed, only newly appended work is delegated to ``executor``.
    """

    _require_extension_prefix(previous, run)
    replay = _PrefixReplayExecutor(_physical_executions(previous), executor)
    staged = execute_staged_workflow_run(
        run,
        registry,
        replay,
        validate_semantic_model=validate_semantic_model,
    )
    replay.require_complete_replay()
    return staged


__all__ = [
    "IncrementalExecutionError",
    "execute_incremental_workflow_run",
]
