from alertissimo.data_layer.representations import (
    InternalEdgeId,
    InternalPortfolioId,
    InternalRecordId,
    Portfolio,
    SemanticEdge,
    SemanticRecord,
)
from alertissimo.data_layer.runtime import edge_builder
from alertissimo.data_layer.runtime.edge_builder import connect_portfolio_records


def record(identifier, semantic_type, fields=None):
    return SemanticRecord(InternalRecordId(identifier), semantic_type, fields or {})


def test_existing_explicit_edges_are_preserved():
    first = record("detection:1", "detection@ztf:lasair")
    second = record("detection:2", "detection@ztf:lasair")
    explicit = SemanticEdge(
        InternalEdgeId("edge:explicit"), "--duplicate--",
        first.internal_record_id, second.internal_record_id,
        {"confidence": 1.0},
    )
    portfolio = Portfolio(InternalPortfolioId("portfolio:1"), (first, second), (explicit,))

    connected = connect_portfolio_records(portfolio)

    assert connected.edges == (explicit,)
    assert connected.records == portfolio.records
    assert connected.executions == portfolio.executions


def test_no_containment_or_summary_hub_edges_are_generated():
    portfolio = Portfolio(InternalPortfolioId("portfolio:2"), (
        record("summary", "summary@ztf:lasair"),
        record("detection:1", "detection@ztf:lasair"),
        record("detection:2", "detection@ztf:lasair"),
        record("classification", "classification@lasair"),
        record("crossmatch", "crossmatch@unknown:lasair"),
    ))

    assert connect_portfolio_records(portfolio).edges == ()


def test_no_chronological_edges_are_generated():
    portfolio = Portfolio(InternalPortfolioId("portfolio:3"), (
        record("detection:1", "detection@ztf:lasair", {"time.mjd": 60000.0}),
        record("detection:2", "detection@ztf:lasair", {"time.mjd": 60001.0}),
    ))

    assert connect_portfolio_records(portfolio).edges == ()


def test_edge_builder_defines_no_invented_edge_carriers():
    values = vars(edge_builder).values()
    assert "--precedes-->" not in values
    assert "--rapid_change_with-->" not in values
