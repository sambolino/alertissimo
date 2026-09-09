"""Provider-independent candidate selection over normalized semantic Portfolios."""

from __future__ import annotations

import math

from alertissimo.data_layer.representations import Portfolio
from alertissimo.orchestration.ir import SearchSelection

from .models import StepPortfolioResult, summary_object_identity


class SearchSelectionError(ValueError):
    """A declared candidate selection cannot be evaluated from semantic evidence."""


def _latest_value(portfolio: Portfolio) -> float:
    values = []
    for record in portfolio.records:
        if record.semantic_type.split("@", 1)[0] != "summary":
            continue
        value = record.fields.get("time.last_mjd")
        if value is None or isinstance(value, bool):
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError, OverflowError) as error:
            raise SearchSelectionError(
                "latest selection requires numeric summary.time.last_mjd values"
            ) from error
        if not math.isfinite(numeric):
            raise SearchSelectionError(
                "latest selection requires finite summary.time.last_mjd values"
            )
        values.append(numeric)
    if not values:
        identity = summary_object_identity(portfolio)
        label = identity if identity is not None else portfolio.internal_portfolio_id.value
        raise SearchSelectionError(
            "latest selection cannot rank candidate without summary.time.last_mjd: "
            f"{label!r}"
        )
    return max(values)


def select_portfolios(
    portfolios: tuple[Portfolio, ...], selection: SearchSelection
) -> tuple[Portfolio, ...]:
    """Apply semantic candidate selection globally after identity consolidation."""

    if selection.latest is None:
        raise SearchSelectionError("unsupported empty search selection")
    ranked = sorted(
        portfolios,
        key=lambda portfolio: (
            -_latest_value(portfolio),
            summary_object_identity(portfolio)
            or ("", portfolio.internal_portfolio_id.value),
        ),
    )
    return tuple(ranked[: selection.latest])


def select_step_portfolios(
    view: StepPortfolioResult, selection: SearchSelection
) -> StepPortfolioResult:
    """Retain physical audit groups while replacing the semantic Step view."""

    return StepPortfolioResult(
        step_index=view.step_index,
        executions=view.executions,
        materialized_portfolios=select_portfolios(view.portfolios, selection),
    )


__all__ = [
    "SearchSelectionError",
    "select_portfolios",
    "select_step_portfolios",
]
