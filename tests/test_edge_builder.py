from alertissimo.data_layer.representations import (
    InternalEdgeId,
    InternalPortfolioId,
    InternalRecordId,
    Portfolio,
    SemanticEdge,
    SemanticRecord,
)
from alertissimo.data_layer.runtime.edge_builder import connect_portfolio_records


def record(identifier, semantic_type, **fields):
    return SemanticRecord(InternalRecordId(identifier), semantic_type, fields)


def test_existing_explicit_edges_are_preserved():
    first = record("detection:1", "detection@ztf:lasair", **{"time.mjd": 60000.0})
    second = record("detection:2", "detection@ztf:lasair", **{"time.mjd": 60001.0})
    duplicate = SemanticEdge(
        InternalEdgeId("edge:duplicate"), "--duplicate--",
        first.internal_record_id, second.internal_record_id,
        {"basis": "explicit upstream assertion"},
    )
    portfolio = Portfolio(InternalPortfolioId("portfolio:1"), (first, second), (duplicate,))

    connected = connect_portfolio_records(portfolio)

    assert connected.edges == (duplicate,)
    assert connected.records == portfolio.records
    assert connected.executions == portfolio.executions


def test_no_containment_or_summary_hub_edges_are_generated():
    records = (
        record("summary", "summary@ztf:lasair"),
        record("detection:1", "detection@ztf:lasair"),
        record("detection:2", "detection@ztf:lasair"),
        record("classification", "classification@lasair"),
        record("crossmatch", "crossmatch@sherlock:lasair"),
    )
    connected = connect_portfolio_records(Portfolio(InternalPortfolioId("portfolio:2"), records))
    assert connected.edges == ()


def test_no_chronological_edges_are_generated():
    records = (
        record("detection:early", "detection@ztf:lasair", **{"time.mjd": 60000.0}),
        record("detection:late", "detection@ztf:lasair", **{"time.mjd": 60001.0}),
    )
    connected = connect_portfolio_records(Portfolio(InternalPortfolioId("portfolio:3"), records))
    assert connected.edges == ()


def test_edge_builder_does_not_define_invented_carriers():
    import inspect
    import alertissimo.data_layer.runtime.edge_builder as edge_builder

    source = inspect.getsource(edge_builder)
    assert "--precedes-->" not in source
    assert "--rapid_change_with-->" not in source
