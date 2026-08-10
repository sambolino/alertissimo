"""Preserve explicit semantic edges without inferring portfolio relationships."""

from __future__ import annotations

from collections.abc import Callable

from alertissimo.data_layer.representations import InternalEdgeId, Portfolio


def connect_portfolio_records(
    portfolio: Portfolio,
    *,
    edge_id_factory: Callable[[], InternalEdgeId] | None = None,
) -> Portfolio:
    """Return a structurally equivalent portfolio without synthesizing edges.

    Automatic containment, summary-hub, and chronological edges are
    intentionally not generated. Edges should be added only for explicit
    ontology-supported assertions.

    ``edge_id_factory`` remains accepted for API compatibility, but is unused
    while the builder performs no inference.
    """
    del edge_id_factory
    return Portfolio(
        internal_portfolio_id=portfolio.internal_portfolio_id,
        records=portfolio.records,
        edges=portfolio.edges,
        executions=portfolio.executions,
    )
