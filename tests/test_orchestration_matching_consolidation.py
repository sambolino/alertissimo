"""MatchStep adjacency must survive semantic Portfolio consolidation."""

from alertissimo.data_layer.representations import (
    InternalPortfolioId,
    InternalRecordId,
    Portfolio,
    SemanticRecord,
)
from alertissimo.orchestration.ir import MatchStep
from alertissimo.orchestration.matching import match_step_portfolios
from alertissimo.orchestration.normalization import ExecutionPortfolioResult, StepPortfolioResult


def _portfolio(identifier: str, record_id: str, origin: str, object_id: str) -> Portfolio:
    return Portfolio(
        InternalPortfolioId(identifier),
        records=(
            SemanticRecord(
                InternalRecordId(record_id),
                f"summary@{origin}:test",
                {
                    "identity.object_id": object_id,
                    "position.ra": 42.0,
                    "position.dec": -10.0,
                },
            ),
        ),
    )


def test_match_edges_remap_from_execution_local_ids_to_consolidated_semantic_ids():
    lsst_a = _portfolio("portfolio:lsst:a", "record:lsst:a", "lsst", "LSST1")
    lsst_b = _portfolio("portfolio:lsst:b", "record:lsst:b", "lsst", "LSST1")
    ztf = _portfolio("portfolio:ztf", "record:ztf", "ztf", "ZTF1")
    source = StepPortfolioResult(
        step_index=0,
        executions=(
            ExecutionPortfolioResult("execution:a", (lsst_a, ztf)),
            ExecutionPortfolioResult("execution:b", (lsst_b,)),
        ),
    )

    matched = match_step_portfolios(
        MatchStep(
            method="position",
            params={
                "candidate_origins": ["lsst", "ztf"],
                "max_angular_separation_arcsec": 1.0,
            },
        ),
        source,
        step_index=1,
    )

    semantic = matched.portfolios
    assert len(semantic) == 2
    lsst, ztf_view = semantic
    assert lsst.internal_portfolio_id not in {
        lsst_a.internal_portfolio_id,
        lsst_b.internal_portfolio_id,
    }
    assert ztf_view.internal_portfolio_id == ztf.internal_portfolio_id
    assert len(lsst.edges) == len(ztf_view.edges) == 1

    left = lsst.edges[0]
    right = ztf_view.edges[0]
    assert left.internal_edge_id == right.internal_edge_id
    assert (left.subject, left.target) == (
        lsst.internal_portfolio_id,
        ztf_view.internal_portfolio_id,
    )
    assert (right.subject, right.target) == (
        ztf_view.internal_portfolio_id,
        lsst.internal_portfolio_id,
    )
