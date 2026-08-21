"""Contracts for local positional MatchStep execution over normalized Portfolios."""

import pytest

from alertissimo.data_layer.representations import (
    InternalPortfolioId,
    InternalRecordId,
    Portfolio,
    SemanticRecord,
)
from alertissimo.orchestration.ir import MatchStep
from alertissimo.orchestration.matching import (
    MatchInputError,
    UnsupportedMatchError,
    match_step_portfolios,
)
from alertissimo.orchestration.normalization import (
    ExecutionPortfolioResult,
    StepPortfolioResult,
)


def _portfolio(identifier: str, origin: str, object_id: str, ra: float, dec: float) -> Portfolio:
    return Portfolio(
        internal_portfolio_id=InternalPortfolioId(identifier),
        records=(
            SemanticRecord(
                InternalRecordId(f"record:{identifier}"),
                f"summary@{origin}:test",
                {
                    "identity.object_id": object_id,
                    "position.ra": ra,
                    "position.dec": dec,
                },
            ),
        ),
    )


def _view(*portfolios: Portfolio) -> StepPortfolioResult:
    return StepPortfolioResult(
        step_index=0,
        executions=(ExecutionPortfolioResult("execution:search", portfolios),),
    )


def _step(threshold: float = 1.0) -> MatchStep:
    return MatchStep(
        method="position",
        params={
            "candidate_origins": ["lsst", "ztf"],
            "max_angular_separation_arcsec": threshold,
        },
    )


def test_position_match_emits_symmetric_portfolio_adjacency_with_shared_edge_id():
    lsst = _portfolio("portfolio:lsst", "lsst", "LSST1", 10.0, 20.0)
    ztf = _portfolio("portfolio:ztf", "ztf", "ZTF1", 10.0001, 20.0)

    matched = match_step_portfolios(_step(), _view(lsst, ztf), step_index=1)

    assert matched.step_index == 1
    assert len(matched.executions) == 1
    matched_lsst, matched_ztf = matched.executions[0].portfolios
    assert len(matched_lsst.edges) == len(matched_ztf.edges) == 1
    left_edge = matched_lsst.edges[0]
    right_edge = matched_ztf.edges[0]
    assert left_edge.internal_edge_id == right_edge.internal_edge_id
    assert left_edge.edge_type == right_edge.edge_type == "--spatially_near--"
    assert left_edge.subject == lsst.internal_portfolio_id
    assert left_edge.target == ztf.internal_portfolio_id
    assert right_edge.subject == ztf.internal_portfolio_id
    assert right_edge.target == lsst.internal_portfolio_id
    assert 0.0 < left_edge.fields["angular_separation"] < 1.0
    assert left_edge.fields["basis"] == "summary.position"


def test_surface_style_position_predicate_executes_without_a_second_match_model():
    lsst = _portfolio("portfolio:lsst", "lsst", "LSST1", 10.0, 20.0)
    ztf = _portfolio("portfolio:ztf", "ztf", "ZTF1", 10.0001, 20.0)
    step = MatchStep(
        params={
            "candidate_origins": ["lsst", "ztf"],
            "predicate": "position within 1arcsec",
        }
    )

    matched = match_step_portfolios(step, _view(lsst, ztf), step_index=1)

    assert matched.step_index == 1
    assert len(matched.portfolios) == 2
    assert all(len(portfolio.edges) == 1 for portfolio in matched.portfolios)


def test_position_match_does_not_merge_or_connect_outside_threshold():
    lsst = _portfolio("portfolio:lsst", "lsst", "LSST1", 10.0, 20.0)
    ztf = _portfolio("portfolio:ztf", "ztf", "ZTF1", 10.01, 20.0)

    matched = match_step_portfolios(_step(), _view(lsst, ztf), step_index=1)

    assert matched.executions[0].portfolios == (lsst, ztf)
    assert matched.portfolios == (lsst, ztf)
    assert all(not portfolio.edges for portfolio in matched.portfolios)


def test_position_match_never_matches_within_one_origin():
    first = _portfolio("portfolio:a", "lsst", "LSST1", 10.0, 20.0)
    second = _portfolio("portfolio:b", "lsst", "LSST2", 10.00001, 20.0)

    matched = match_step_portfolios(
        MatchStep(
            method="position",
            params={
                "candidate_origins": ["lsst", "ztf"],
                "max_angular_separation_arcsec": 10.0,
            },
        ),
        _view(first, second),
        step_index=1,
    )

    assert all(not portfolio.edges for portfolio in matched.executions[0].portfolios)


def test_position_match_rejects_ambiguous_object_summary_position():
    portfolio = Portfolio(
        InternalPortfolioId("portfolio:ambiguous"),
        records=(
            SemanticRecord(
                InternalRecordId("record:1"),
                "summary@lsst:test",
                {"identity.object_id": "LSST1", "position.ra": 10.0, "position.dec": 20.0},
            ),
            SemanticRecord(
                InternalRecordId("record:2"),
                "summary@lsst:test",
                {"identity.object_id": "LSST1", "position.ra": 11.0, "position.dec": 20.0},
            ),
        ),
    )
    ztf = _portfolio("portfolio:ztf", "ztf", "ZTF1", 10.0, 20.0)

    with pytest.raises(MatchInputError, match="unambiguous object-level summary position"):
        match_step_portfolios(_step(), _view(portfolio, ztf), step_index=1)


def test_conflicting_structured_and_predicate_thresholds_are_rejected():
    lsst = _portfolio("portfolio:lsst", "lsst", "LSST1", 10.0, 20.0)
    ztf = _portfolio("portfolio:ztf", "ztf", "ZTF1", 10.0, 20.0)

    with pytest.raises(UnsupportedMatchError, match="conflicting"):
        match_step_portfolios(
            MatchStep(
                method="position",
                params={
                    "candidate_origins": ["lsst", "ztf"],
                    "max_angular_separation_arcsec": 1.0,
                    "predicate": "position within 2arcsec",
                },
            ),
            _view(lsst, ztf),
            step_index=1,
        )


def test_first_match_executor_refuses_temporal_and_external_semantics():
    lsst = _portfolio("portfolio:lsst", "lsst", "LSST1", 10.0, 20.0)
    ztf = _portfolio("portfolio:ztf", "ztf", "ZTF1", 10.0, 20.0)

    with pytest.raises(UnsupportedMatchError, match="temporal"):
        match_step_portfolios(
            MatchStep(
                method="position",
                params={
                    "candidate_origins": ["lsst", "ztf"],
                    "max_angular_separation_arcsec": 1.0,
                    "max_time_delta": "3d",
                },
            ),
            _view(lsst, ztf),
            step_index=1,
        )
