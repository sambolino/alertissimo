"""Immutable workflow-occurrence wrappers around normalized portfolios."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from uuid import uuid4

from alertissimo.data_layer.representations import (
    InternalPortfolioId,
    Portfolio,
    SemanticEdge,
)
from alertissimo.orchestration.runtime import WorkflowRun


def summary_object_identity(portfolio: Portfolio) -> tuple[str, str] | None:
    """Return one positively established ``(origin, object_id)`` summary identity.

    Only primary ``summary`` records participate. IDs on detections, crossmatches,
    or other semantic records may identify those records rather than the Portfolio's
    astronomical object and therefore are not safe consolidation evidence.

    Ambiguous, malformed, unknown-origin, and identity-less Portfolios deliberately
    return ``None`` and remain independent at the Step boundary.
    """

    identities: set[tuple[str, str]] = set()
    for record in portfolio.records:
        family, separator, qualifier = record.semantic_type.partition("@")
        if family != "summary" or not separator:
            continue
        origin, producer_separator, _producer = qualifier.partition(":")
        if not producer_separator or not origin or origin == "unknown":
            continue
        object_id = record.get("identity.object_id")
        if object_id is None:
            continue
        identities.add((origin, str(object_id)))
    if len(identities) != 1:
        return None
    return next(iter(identities))


# Backward-compatible private spelling for code written before MatchStep needed the
# exact same identity rule outside this module.
_summary_object_identity = summary_object_identity


def _unique_portfolios(portfolios: list[Portfolio]) -> tuple[Portfolio, ...]:
    """Deduplicate repeated references to the same canonical Portfolio safely."""

    by_id: dict[str, Portfolio] = {}
    ordered: list[Portfolio] = []
    for portfolio in portfolios:
        identifier = portfolio.internal_portfolio_id.value
        existing = by_id.get(identifier)
        if existing is None:
            by_id[identifier] = portfolio
            ordered.append(portfolio)
        elif existing != portfolio:
            raise ValueError(
                "cannot consolidate Portfolios with conflicting content under "
                f"internal portfolio ID {identifier!r}"
            )
    return tuple(ordered)


def _unique_components(portfolios: tuple[Portfolio, ...], attribute: str, id_attribute: str):
    """Union Portfolio components by immutable internal ID, preserving first order."""

    by_id = {}
    ordered = []
    for portfolio in portfolios:
        for item in getattr(portfolio, attribute):
            identifier = getattr(item, id_attribute).value
            existing = by_id.get(identifier)
            if existing is None:
                by_id[identifier] = item
                ordered.append(item)
            elif existing != item:
                raise ValueError(
                    f"cannot consolidate conflicting {attribute} under internal ID "
                    f"{identifier!r}"
                )
    return tuple(ordered)


def _remap_portfolio_edge(
    edge: SemanticEdge,
    portfolio_id_map: dict[InternalPortfolioId, InternalPortfolioId],
) -> SemanticEdge:
    """Rewrite Portfolio-edge endpoints to their consolidated semantic IDs."""

    if not isinstance(edge.subject, InternalPortfolioId):
        return edge
    subject = portfolio_id_map.get(edge.subject, edge.subject)
    target = portfolio_id_map.get(edge.target, edge.target)
    if subject == edge.subject and target == edge.target:
        return edge
    return SemanticEdge(
        internal_edge_id=edge.internal_edge_id,
        edge_type=edge.edge_type,
        subject=subject,
        target=target,
        fields=edge.fields,
        internal_source=edge.internal_source,
    )


def _unique_edges(
    portfolios: tuple[Portfolio, ...],
    portfolio_id_map: dict[InternalPortfolioId, InternalPortfolioId],
) -> tuple[SemanticEdge, ...]:
    """Union edges after rewriting any constituent Portfolio endpoints."""

    by_id: dict[str, SemanticEdge] = {}
    ordered: list[SemanticEdge] = []
    for portfolio in portfolios:
        for original in portfolio.edges:
            edge = _remap_portfolio_edge(original, portfolio_id_map)
            identifier = edge.internal_edge_id.value
            existing = by_id.get(identifier)
            if existing is None:
                by_id[identifier] = edge
                ordered.append(edge)
            elif existing != edge:
                raise ValueError(
                    "cannot consolidate conflicting edges under internal ID "
                    f"{identifier!r}"
                )
    return tuple(ordered)


def _merge_portfolio_group(
    portfolios: tuple[Portfolio, ...],
    *,
    final_id: InternalPortfolioId,
    portfolio_id_map: dict[InternalPortfolioId, InternalPortfolioId],
) -> Portfolio:
    """Merge one positively identity-equivalent group without field fusion."""

    edges = _unique_edges(portfolios, portfolio_id_map)
    if len(portfolios) == 1:
        portfolio = portfolios[0]
        if portfolio.internal_portfolio_id == final_id and portfolio.edges == edges:
            return portfolio
        return Portfolio(
            internal_portfolio_id=final_id,
            records=portfolio.records,
            edges=edges,
            executions=portfolio.executions,
        )

    return Portfolio(
        internal_portfolio_id=final_id,
        records=_unique_components(portfolios, "records", "internal_record_id"),
        edges=edges,
        executions=_unique_components(
            portfolios, "executions", "internal_execution_id"
        ),
    )


def consolidate_portfolios(portfolios: tuple[Portfolio, ...]) -> tuple[Portfolio, ...]:
    """Consolidate one semantic Portfolio material view by exact object identity.

    The operation is intentionally independent of workflow-Step ownership. It is
    used both for the ordinary semantic view of one Step's own normalized physical
    executions and for an explicitly materialized snapshot that combines inherited
    semantic material with evidence retrieved by the current Step.

    Portfolios merge only when their primary summary records establish the same
    ``(origin, object_id)``. Unidentified or ambiguous Portfolios remain distinct.
    Records, edges, and execution provenance are unioned by their immutable internal
    IDs; no record-level fields are fused or guessed.
    """

    groups: dict[tuple[str, ...], list[Portfolio]] = {}
    order: list[tuple[str, ...]] = []
    for portfolio in portfolios:
        identity = summary_object_identity(portfolio)
        if identity is None:
            key = ("portfolio", portfolio.internal_portfolio_id.value)
        else:
            key = ("identity", *identity)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(portfolio)

    unique_groups = {key: _unique_portfolios(groups[key]) for key in order}
    final_ids: dict[tuple[str, ...], InternalPortfolioId] = {}
    portfolio_id_map: dict[InternalPortfolioId, InternalPortfolioId] = {}
    for key in order:
        grouped = unique_groups[key]
        final_id = (
            grouped[0].internal_portfolio_id
            if len(grouped) == 1
            else InternalPortfolioId(f"portfolio:{uuid4().hex}")
        )
        final_ids[key] = final_id
        for portfolio in grouped:
            existing = portfolio_id_map.get(portfolio.internal_portfolio_id)
            if existing is not None and existing != final_id:
                raise ValueError(
                    "one internal Portfolio ID cannot consolidate into multiple "
                    "semantic Portfolio IDs"
                )
            portfolio_id_map[portfolio.internal_portfolio_id] = final_id

    return tuple(
        _merge_portfolio_group(
            unique_groups[key],
            final_id=final_ids[key],
            portfolio_id_map=portfolio_id_map,
        )
        for key in order
    )


def _consolidate_step_portfolios(
    executions: tuple["ExecutionPortfolioResult", ...],
) -> tuple[Portfolio, ...]:
    """Build one Step's semantic view from that Step's own physical executions."""

    return consolidate_portfolios(
        tuple(
            portfolio
            for execution in executions
            for portfolio in execution.portfolios
        )
    )


@dataclass(frozen=True)
class ExecutionPortfolioResult:
    """Zero or more object Portfolios produced by one physical execution."""

    execution_id: str
    portfolios: tuple[Portfolio, ...]


@dataclass(frozen=True)
class StepPortfolioResult:
    """Normalized output for one workflow Step occurrence.

    ``executions`` preserves the physical/audit grouping owned by this Step exactly
    as normalized from its provider calls. ``portfolios`` is the semantic Step view.

    Normally the semantic view is consolidated directly from ``executions``. When a
    Step enriches or locally transforms an earlier semantic view,
    ``materialized_portfolios`` stores that immutable occurrence-aligned snapshot.
    This keeps historical Step views unchanged while avoiding the false claim that
    inherited provider executions physically belong to the later Step.
    """

    step_index: int
    executions: tuple[ExecutionPortfolioResult, ...]
    materialized_portfolios: tuple[Portfolio, ...] | None = None

    @cached_property
    def portfolios(self) -> tuple[Portfolio, ...]:
        """Return the cached per-object semantic view for this Step occurrence."""

        if self.materialized_portfolios is not None:
            return consolidate_portfolios(self.materialized_portfolios)
        return _consolidate_step_portfolios(self.executions)


@dataclass(frozen=True)
class WorkflowPortfolioResult:
    """A WorkflowRun and its occurrence-aligned normalized output."""

    run: WorkflowRun
    steps: tuple[StepPortfolioResult, ...]


__all__ = [
    "ExecutionPortfolioResult",
    "StepPortfolioResult",
    "WorkflowPortfolioResult",
    "consolidate_portfolios",
    "summary_object_identity",
]
