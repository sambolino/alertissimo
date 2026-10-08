"""Reduce a complete normalized candidate universe using canonical selection."""

from __future__ import annotations

import math

from alertissimo.orchestration.ir import SearchStep, Step

from .models import StepPortfolioResult, summary_object_identity


class SearchSelectionError(ValueError):
    """A candidate has no trustworthy identity or numeric recency value."""


def apply_search_selection(step: Step, view: StepPortfolioResult) -> StepPortfolioResult:
    """Apply latest once, after residual pruning and object consolidation.

    Physical execution groups remain available for audit. The selected immutable
    material snapshot supplies downstream IDs and final semantic results. No
    per-page, per-source, or per-batch limits are imposed here.
    """
    if not isinstance(step, SearchStep) or step.selection is None:
        return view
    if step.semantic_type != "summary":
        raise SearchSelectionError("latest currently requires summary candidates")
    ranked = []
    for portfolio in view.portfolios:
        identity = summary_object_identity(portfolio)
        if identity is None:
            raise SearchSelectionError("latest candidate lacks an unambiguous summary object identity")
        origin, object_id = identity
        values = []
        for record in portfolio.records:
            if (
                not record.semantic_type.startswith(f"summary@{origin}:")
                or str(record.get("identity.object_id")) != object_id
            ):
                continue
            value = record.get("time.last_mjd")
            if value is None:
                continue
            if type(value) not in (int, float) or not math.isfinite(value):
                raise SearchSelectionError(f"latest candidate {identity!r} has a non-finite/non-numeric recency value")
            values.append(value)
        if not values:
            raise SearchSelectionError(f"latest candidate {identity!r} lacks summary.time.last_mjd")
        # Repeated provider records do not increase candidate cardinality. Keep
        # every record; choose the most recent known detection for this object.
        ranked.append((-max(values), identity, portfolio))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return StepPortfolioResult(
        step_index=view.step_index,
        executions=view.executions,
        materialized_portfolios=tuple(item[2] for item in ranked[:step.selection.latest]),
    )
