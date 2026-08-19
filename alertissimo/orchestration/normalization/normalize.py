"""Bridge successful orchestration results to data-layer normalization."""

from __future__ import annotations

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import Portfolio
from alertissimo.data_layer.runtime.record_builder import build_portfolios_from_execution
from alertissimo.orchestration.ir import DeriveStep
from alertissimo.orchestration.runtime import (
    StepExecutionResult,
    StepRunState,
    WorkflowExecutionResult,
)

from .models import (
    ExecutionPortfolioResult,
    StepPortfolioResult,
    WorkflowPortfolioResult,
)


class WorkflowNormalizationAlignmentError(ValueError):
    """Raised before normalization when runtime results are cross-wired."""


def normalize_execution(
    execution: ExecutionResult,
    *,
    validate_semantic_model: bool = True,
) -> tuple[Portfolio, ...]:
    """Normalize exactly one physical result using the authoritative builder.

    Validation defaults on because orchestration is a production boundary from
    physical provider data into the canonical semantic model.
    """

    return build_portfolios_from_execution(
        execution, validate_semantic_model=validate_semantic_model
    )


def normalize_step_execution(
    result: StepExecutionResult,
    *,
    validate_semantic_model: bool = True,
) -> StepPortfolioResult:
    """Normalize a completed Step result, including one from a failure path."""

    return StepPortfolioResult(
        step_index=result.step_index,
        executions=tuple(
            ExecutionPortfolioResult(
                execution_id=execution.internal_execution_id.value,
                portfolios=normalize_execution(
                    execution,
                    validate_semantic_model=validate_semantic_model,
                ),
            )
            for execution in result.executions
        ),
    )


def _validate_workflow_alignment(result: WorkflowExecutionResult) -> None:
    run = result.run
    if len(result.steps) != len(run.steps):
        raise WorkflowNormalizationAlignmentError(
            "execution Step result count does not match WorkflowRun StepRun count "
            f"({len(result.steps)} != {len(run.steps)})"
        )

    for position, (step_run, step_result) in enumerate(zip(run.steps, result.steps)):
        if step_result.step_index != step_run.step_index:
            raise WorkflowNormalizationAlignmentError(
                f"execution Step result at position {position} has step_index "
                f"{step_result.step_index}; expected {step_run.step_index}"
            )

        step = run.step_at(step_run.step_index)
        if isinstance(step, DeriveStep):
            if step_run.state is not StepRunState.PLANNED:
                raise WorkflowNormalizationAlignmentError(
                    f"derive step_index {step_run.step_index} is {step_run.state.value}; "
                    "it must remain planned until post-normalization derivation"
                )
            if step_run.endpoint_plans or step_run.execution_ids or step_result.executions:
                raise WorkflowNormalizationAlignmentError(
                    f"derive step_index {step_run.step_index} must have no physical "
                    "endpoint plans, execution IDs, or execution results"
                )
            continue

        if step_run.state is not StepRunState.SUCCEEDED:
            raise WorkflowNormalizationAlignmentError(
                f"step_index {step_run.step_index} is {step_run.state.value}; "
                "workflow normalization requires succeeded state"
            )
        if len(step_run.endpoint_plans) != len(step_result.executions):
            raise WorkflowNormalizationAlignmentError(
                f"step_index {step_run.step_index} endpoint plan count does not "
                "match execution result count "
                f"({len(step_run.endpoint_plans)} != "
                f"{len(step_result.executions)})"
            )
        for execution_position, (plan, execution) in enumerate(
            zip(step_run.endpoint_plans, step_result.executions)
        ):
            provenance = execution.execution_provenance
            planned_identity = (plan.broker, plan.origin, plan.endpoint)
            actual_identity = (
                provenance.broker,
                provenance.origin,
                provenance.endpoint,
            )
            if planned_identity != actual_identity:
                raise WorkflowNormalizationAlignmentError(
                    f"step_index {step_run.step_index} execution position "
                    f"{execution_position} endpoint identity does not align: "
                    f"planned broker={plan.broker}, origin={plan.origin}, "
                    f"endpoint={plan.endpoint}; actual broker={provenance.broker}, "
                    f"origin={provenance.origin}, endpoint={provenance.endpoint}"
                )
        actual_ids = tuple(
            execution.internal_execution_id.value
            for execution in step_result.executions
        )
        if actual_ids != step_run.execution_ids:
            raise WorkflowNormalizationAlignmentError(
                f"step_index {step_run.step_index} execution IDs do not align in "
                f"order (StepRun has {step_run.execution_ids}, results have {actual_ids})"
            )


def normalize_workflow_execution(
    result: WorkflowExecutionResult,
    *,
    validate_semantic_model: bool = True,
) -> WorkflowPortfolioResult:
    """Normalize physical results while preserving endpoint-free derive occurrences."""

    # Complete validation first: malformed results must not produce partial output.
    _validate_workflow_alignment(result)
    return WorkflowPortfolioResult(
        run=result.run,
        steps=tuple(
            normalize_step_execution(
                step, validate_semantic_model=validate_semantic_model
            )
            for step in result.steps
        ),
    )


__all__ = [
    "WorkflowNormalizationAlignmentError",
    "normalize_execution",
    "normalize_step_execution",
    "normalize_workflow_execution",
]
