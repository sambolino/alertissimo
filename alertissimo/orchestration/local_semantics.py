"""Finalize post-normalization semantic workflow steps in occurrence order."""

from __future__ import annotations

from alertissimo.orchestration.derivation import derive_portfolio
from alertissimo.orchestration.ir import DeriveStep, MatchStep
from alertissimo.orchestration.matching import match_step_portfolios
from alertissimo.orchestration.normalization import (
    ExecutionPortfolioResult,
    StepPortfolioResult,
    WorkflowPortfolioResult,
    consolidate_portfolios,
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
    """Complement all earlier semantic views, preserving their material snapshots."""

    for prior_index in range(step_index):
        prior = steps[prior_index]
        derived_executions = tuple(
            ExecutionPortfolioResult(
                execution_id=execution.execution_id,
                portfolios=tuple(
                    derive_portfolio(step, portfolio, step_index=step_index)
                    for portfolio in execution.portfolios
                ),
            )
            for execution in prior.executions
        )
        materialized = None
        if prior.materialized_portfolios is not None:
            materialized = tuple(
                derive_portfolio(step, portfolio, step_index=step_index)
                for portfolio in prior.portfolios
            )
        steps[prior_index] = StepPortfolioResult(
            step_index=prior.step_index,
            executions=derived_executions,
            materialized_portfolios=materialized,
        )


def _rematerialize_provider_step(
    *,
    step_index: int,
    step_run,
    steps: list[StepPortfolioResult],
) -> None:
    """Rebuild one provider Step snapshot from its now-finalized semantic input.

    Initial normalization may run before a preceding MatchStep has produced its local
    semantic view. Replaying only semantic materialization here keeps physical
    execution ownership untouched while ensuring downstream provider Steps inherit
    the finalized Filter/Match/derivation state rather than an earlier placeholder.
    """

    reference = step_run.candidate_input_from
    if reference is None or not step_run.endpoint_plans:
        return
    if reference.step_index >= step_index:
        raise LocalSemanticExecutionError(
            f"provider step_index {step_index} material input must reference an earlier Step"
        )
    try:
        source = steps[reference.step_index]
    except IndexError as exc:
        raise LocalSemanticExecutionError(
            f"provider step_index {step_index} references unavailable material Step "
            f"{reference.step_index}"
        ) from exc
    current = steps[step_index]
    own = StepPortfolioResult(
        step_index=step_index,
        executions=current.executions,
    )
    steps[step_index] = StepPortfolioResult(
        step_index=step_index,
        executions=current.executions,
        materialized_portfolios=consolidate_portfolios(
            source.portfolios + own.portfolios
        ),
    )


def finalize_local_semantics(
    result: WorkflowPortfolioResult,
) -> WorkflowPortfolioResult:
    """Finalize local operations and semantic material lineage in workflow order.

    No local semantic Step fabricates physical execution provenance. Derivations keep
    their established behavior of complementing earlier Portfolio views. MatchStep
    exposes its own occurrence-aligned relationally filtered Portfolio view: only
    candidates participating in an accepted Match relation propagate, annotated with
    the corresponding Portfolio adjacency edges. A later provider Step then
    rematerializes its semantic snapshot from that finalized local view plus only its
    own newly normalized physical output.
    """

    steps = list(result.steps)
    run = result.run

    for step_index, step in enumerate(run.workflow.steps):
        step_run = run.steps[step_index]

        if not isinstance(step, (DeriveStep, MatchStep)):
            _rematerialize_provider_step(
                step_index=step_index,
                step_run=step_run,
                steps=steps,
            )
            continue

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
