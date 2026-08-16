"""Bridge successful orchestration results to data-layer normalization."""

from __future__ import annotations

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import Portfolio
from alertissimo.data_layer.runtime.record_builder import build_portfolio_from_execution
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
) -> Portfolio:
    """Normalize exactly one physical result using the authoritative builder.

    Validation defaults on because orchestration is a production boundary from
    physical provider data into the canonical semantic model.
    """

    return build_portfolio_from_execution(
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
        portfolios=tuple(
            ExecutionPortfolioResult(
                execution_id=execution.internal_execution_id.value,
                portfolio=normalize_execution(
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
        if step_run.state is not StepRunState.SUCCEEDED:
            raise WorkflowNormalizationAlignmentError(
                f"step_index {step_run.step_index} is {step_run.state.value}; "
                "workflow normalization requires succeeded state"
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
    """Validate associations, then independently normalize every execution."""

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
