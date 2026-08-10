"""Build conservative internal associations between portfolio records."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from alertissimo.data_layer.representations import (
    InternalEdgeId,
    Portfolio,
    SemanticEdge,
    SemanticRecord,
)


ASSOCIATION_EDGE_TYPE = "--association--"


def new_internal_edge_id() -> InternalEdgeId:
    """Return a new opaque identifier for an internally generated edge."""
    return InternalEdgeId(f"edge:{uuid4().hex}")


def _execution_id(record: SemanticRecord) -> object | None:
    source = record.internal_source
    return source.internal_execution_id if source is not None else None


def _edge_fields(subject: SemanticRecord, target: SemanticRecord, rule: str) -> dict[str, str]:
    fields = {
        "basis": "same_execution_summary_context",
        "rule": rule,
        "subject_semantic_type": subject.semantic_type,
        "target_semantic_type": target.semantic_type,
    }
    if subject.internal_source is not None:
        fields["subject_payload_key"] = subject.internal_source.payload_key
    if target.internal_source is not None:
        fields["target_payload_key"] = target.internal_source.payload_key
    return fields


def connect_portfolio_records(
    portfolio: Portfolio,
    *,
    edge_id_factory: Callable[[], InternalEdgeId] | None = None,
) -> Portfolio:
    """Associate semantic records with an unambiguous summary record.

    A sole summary owns records from its execution context.  With multiple
    summaries, an exact ``identity.object_id`` match is additionally required.
    Existing equivalent associations are retained rather than duplicated.
    """
    summaries = tuple(
        record for record in portfolio.records
        if record.semantic_type.split("@", 1)[0] == "summary"
    )
    if not summaries:
        return Portfolio(
            portfolio.internal_portfolio_id,
            portfolio.records,
            portfolio.edges,
            portfolio.executions,
        )

    make_edge_id = edge_id_factory or new_internal_edge_id
    existing = {
        (edge.edge_type, edge.subject_record_id, edge.target_record_id)
        for edge in portfolio.edges
    }
    generated: list[SemanticEdge] = []
    for record in portfolio.records:
        if record.semantic_type.split("@", 1)[0] == "summary":
            continue
        candidates = [
            summary for summary in summaries
            if _execution_id(record) == _execution_id(summary)
        ]
        rule = "single_summary_record"
        if len(summaries) != 1:
            object_id = record.get("identity.object_id")
            candidates = [
                summary for summary in candidates
                if object_id is not None
                and summary.get("identity.object_id") == object_id
            ]
            rule = "matching_identity_object_id"
        if len(candidates) != 1:
            continue
        summary = candidates[0]
        signature = (
            ASSOCIATION_EDGE_TYPE,
            record.internal_record_id,
            summary.internal_record_id,
        )
        if signature in existing:
            continue
        generated.append(SemanticEdge(
            internal_edge_id=make_edge_id(),
            edge_type=ASSOCIATION_EDGE_TYPE,
            subject_record_id=record.internal_record_id,
            target_record_id=summary.internal_record_id,
            fields=_edge_fields(record, summary, rule),
            internal_source=None,
        ))
        existing.add(signature)

    return Portfolio(
        internal_portfolio_id=portfolio.internal_portfolio_id,
        records=portfolio.records,
        edges=tuple((*portfolio.edges, *generated)),
        executions=portfolio.executions,
    )
