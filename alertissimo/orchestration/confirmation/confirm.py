"""Existence- and proposition-quorum semantics for ``ConfirmStep``.

A Confirm occurrence owns real provider lookup/evidence executions, then evaluates a
local quorum over those normalized execution-local Portfolios. One broker contributes
at most one vote for one exact semantic object identity, regardless of how many
records or execution-local Portfolios that broker returned.
"""

from __future__ import annotations

from collections import defaultdict

from alertissimo.data_layer.representations import Portfolio
from alertissimo.orchestration.ir import ConfirmStep
from alertissimo.orchestration.normalization.models import (
    StepPortfolioResult,
    consolidate_portfolios,
    summary_object_identity,
)
from alertissimo.orchestration.normalization.predicate import evaluate_portfolio_predicate


class ConfirmExecutionError(ValueError):
    """Raised when confirmation evidence cannot be attributed unambiguously."""


def _execution_broker(execution_id: str, portfolios: tuple[Portfolio, ...]) -> str:
    brokers = {
        provenance.broker
        for portfolio in portfolios
        for provenance in portfolio.executions
        if provenance.internal_execution_id.value == execution_id
    }
    if len(brokers) != 1:
        raise ConfirmExecutionError(
            "confirm execution must resolve to exactly one broker from normalized "
            f"provenance; execution_id={execution_id!r}, brokers={sorted(brokers)!r}"
        )
    return next(iter(brokers))


def _declared_brokers(step: ConfirmStep) -> frozenset[str]:
    return frozenset(source.broker for source in step.sources if source.broker is not None)


def _portfolio_attests(step: ConfirmStep, portfolio: Portfolio) -> bool:
    if step.predicate is None:
        return True
    return evaluate_portfolio_predicate(portfolio, step.predicate)


def confirm_step_portfolios(
    step: ConfirmStep,
    source: StepPortfolioResult,
    own: StepPortfolioResult,
    *,
    step_index: int,
) -> StepPortfolioResult:
    """Return the Confirm occurrence view after distinct-broker quorum.

    ``source`` is the immutable candidate/material view entering Confirm. ``own``
    contains only this Confirm occurrence's normalized physical executions. For bare
    confirmation, a vote means that one execution produced the same exact
    ``(origin, object_id)`` identity as an entering candidate. For proposition
    confirmation, that execution-local Portfolio must additionally satisfy
    ``step.predicate``.

    The resulting Step keeps all of Confirm's occurrence-local physical execution
    groups for audit, while ``materialized_portfolios`` contains only candidates
    meeting the quorum plus the new evidence accumulated for those survivors.
    """

    if step.required_agreement < 1:  # IR validation normally guards this.
        raise ConfirmExecutionError("confirm required_agreement must be positive")

    candidate_identities = {
        identity
        for portfolio in source.portfolios
        for identity in [summary_object_identity(portfolio)]
        if identity is not None
    }
    declared_brokers = _declared_brokers(step)
    votes: dict[tuple[str, str], set[str]] = defaultdict(set)

    for execution in own.executions:
        if not execution.portfolios:
            continue
        broker = _execution_broker(execution.execution_id, execution.portfolios)
        if declared_brokers and broker not in declared_brokers:
            raise ConfirmExecutionError(
                f"confirm execution broker {broker!r} is not one of the declared sources"
            )
        for portfolio in execution.portfolios:
            identity = summary_object_identity(portfolio)
            if (
                identity is not None
                and identity in candidate_identities
                and _portfolio_attests(step, portfolio)
            ):
                votes[identity].add(broker)

    survivors = {
        identity
        for identity in candidate_identities
        if len(votes.get(identity, ())) >= step.required_agreement
    }

    accumulated = consolidate_portfolios(source.portfolios + own.portfolios)
    materialized = tuple(
        portfolio
        for portfolio in accumulated
        if summary_object_identity(portfolio) in survivors
    )
    return StepPortfolioResult(
        step_index=step_index,
        executions=own.executions,
        materialized_portfolios=materialized,
    )
