"""Finalize post-normalization semantic workflow steps in occurrence order."""

from __future__ import annotations

from alertissimo.orchestration.derivation import derive_portfolio
from alertissimo.orchestration.ir import DeriveStep, MatchStep
from alertissimo.orchestration.matching import match_step_portfolios
from alertissimo.orchestration.normalization import (
    ExecutionPortfolioResult,
    StepPortfolioResult,
    WorkflowPortfolioResult,
)
from alertissimo.orchestration.runtime import StepRunState


class LocalSemanticExecutionError(ValueError):
    """Raised when a local semantic Step cannot consume its declared prior view."""


def _mark_succeeded(run, step_index: int):
    step_run = run.steps[step_index].model_copy(
        update={"state": StepRunState.SUCCEEDED, "execution_ids": (), "error": None}
    )
    steps = list(run.steps)
    steps[step_index] = step_run
    return run.model_copy(update={"steps": tuple(steps)})


def _apply_derivation(
    step: DeriveStep,
    *,
    step_index: int,
    steps: list[StepPortfolioResult],
) -> None:
    """Complement all earlier semantic views, preserving the existing contract."""

    for prior_index in range(step_index):
        prior = steps[prior_index]
        steps[prior_index] = StepPortfolioResult(
            step_index=prior.step_index,
            executions=tuple(
                ExecutionPortfolioResult(
                    execution_id=execution.execution_id,
                    portfolios=tuple(
                        derive_portfolio(step, portfolio, step_index=step_index)
                        for portfolio in execution.portfolios
                    ),
                )
                for execution in prior.executions
            ),
        )


def finalize_local_semantics(
    result: WorkflowPortfolioResult,
) -> WorkflowPortfolioResult:
    """Execute DeriveStep and MatchStep after normalization in workflow order.

    No local semantic Step fabricates physical execution provenance. Derivations keep
    their established behavior of complementing earlier Portfolio views. MatchStep
    instead exposes its own occurrence-aligned Portfolio view, copied from the
    planner-declared candidate/material input and annotated with Portfolio adjacency
    edges. Local steps become succeeded only after their semantic work completes.
    """

    steps = list(result.steps)
    run = result.run

    for step_index, step in enumerate(run.workflow.steps):
        if not isinstance(step, (DeriveStep, MatchStep)):
            continue
        step_run = run.steps[step_index]
        if step_run.state is not StepRunState.PLANNED:
            raise LocalSemanticExecutionError(
                f"local semantic step_index {step_index} must be planned before execution"
            )

        if isinstance(step, DeriveStep):
            _apply_derivation(step, step_index=step_index, steps=steps)
        else:
            reference = step_run.candidate_input_from
            if reference is None or reference.step_index >= step_index:
                raise LocalSemanticExecutionError(
                    f"match step_index {step_index} must reference an earlier "
                    "candidate/material Step"
                )
            try:
                source = steps[reference.step_index]
            except IndexError as exc:
                raise LocalSemanticExecutionError(
                    f"match step_index {step_index} references unavailable Step "
                    f"{reference.step_index}"
                ) from exc
            steps[step_index] = match_step_portfolios(
                step,
                source,
                step_index=step_index,
            )

        run = _mark_succeeded(run, step_index)

    return WorkflowPortfolioResult(run=run, steps=tuple(steps))


__all__ = ["LocalSemanticExecutionError", "finalize_local_semantics"]
