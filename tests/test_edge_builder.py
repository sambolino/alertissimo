from itertools import count

from alertissimo.data_layer.representations import (
    InternalEdgeId,
    InternalPortfolioId,
    InternalRecordId,
    Portfolio,
    SemanticRecord,
)
from alertissimo.data_layer.runtime.edge_builder import connect_portfolio_records


def record(identifier, semantic_type, object_id=None):
    fields = {} if object_id is None else {"identity.object_id": object_id}
    return SemanticRecord(InternalRecordId(identifier), semantic_type, fields)


def factory():
    numbers = count(1)
    return lambda: InternalEdgeId(f"edge:{next(numbers)}")


def test_single_summary_connects_non_summary_records():
    summary = record("summary", "summary@ztf:lasair", "ZTF1")
    others = (
        record("detection:1", "detection@ztf:lasair"),
        record("detection:2", "detection@ztf:lasair"),
        record("classification", "classification@lasair"),
    )
    connected = connect_portfolio_records(
        Portfolio(InternalPortfolioId("portfolio:1"), (summary, *others)),
        edge_id_factory=factory(),
    )
    assert len(connected.edges) == 3
    assert {edge.edge_type for edge in connected.edges} == {"--association--"}
    assert {edge.subject_record_id for edge in connected.edges} == {
        item.internal_record_id for item in others
    }
    assert {edge.target_record_id for edge in connected.edges} == {summary.internal_record_id}
    assert all(edge.get("basis") == "same_execution_summary_context" for edge in connected.edges)
    assert all(edge.get("rule") == "single_summary_record" for edge in connected.edges)


def test_no_duplicate_edges():
    portfolio = Portfolio(InternalPortfolioId("portfolio:2"), (
        record("summary", "summary@ztf:lasair"),
        record("detection", "detection@ztf:lasair"),
    ))
    once = connect_portfolio_records(portfolio, edge_id_factory=factory())
    twice = connect_portfolio_records(once, edge_id_factory=factory())
    assert twice.edges == once.edges


def test_multiple_summaries_require_clear_object_id_match():
    first = record("summary:1", "summary@ztf:lasair", "ZTF1")
    second = record("summary:2", "summary@ztf:lasair", "ZTF2")
    matched = record("detection:matched", "detection@ztf:lasair", "ZTF2")
    unmatched = record("detection:unmatched", "detection@ztf:lasair")
    connected = connect_portfolio_records(
        Portfolio(InternalPortfolioId("portfolio:3"), (first, second, matched, unmatched)),
        edge_id_factory=factory(),
    )
    assert len(connected.edges) == 1
    assert connected.edges[0].subject_record_id == matched.internal_record_id
    assert connected.edges[0].target_record_id == second.internal_record_id
    assert connected.edges[0].get("rule") == "matching_identity_object_id"


def test_no_summary_means_no_edges():
    portfolio = Portfolio(InternalPortfolioId("portfolio:4"), (
        record("detection", "detection@ztf:lasair"),
    ))
    assert connect_portfolio_records(portfolio).edges == ()
