"""Keep the extension point for explicit connections between portfolio records."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from alertissimo.data_layer.representations import InternalEdgeId, Portfolio


def new_internal_edge_id() -> InternalEdgeId:
    """Return a new opaque identifier for an internally generated edge."""
    return InternalEdgeId(f"edge:{uuid4().hex}")


def connect_portfolio_records(
    portfolio: Portfolio,
    *,
    edge_id_factory: Callable[[], InternalEdgeId] | None = None,
) -> Portfolio:
    """Return *portfolio* without inferring record-to-record connections.

    Automatic containment, summary-hub, and chronological edges are
    intentionally not generated. Edges should be added only for explicit
    ontology-supported assertions. ``edge_id_factory`` remains part of this
    extension point for future explicit rules.
    """
    del edge_id_factory
    return Portfolio(
        internal_portfolio_id=portfolio.internal_portfolio_id,
        records=portfolio.records,
        edges=portfolio.edges,
        executions=portfolio.executions,
    )
