"""Same survey object identity is harmonization input, never a Match edge."""

from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
    InternalPortfolioId,
    InternalRecordId,
    Portfolio,
    SemanticRecord,
)
from alertissimo.orchestration.ir import MatchStep
from alertissimo.orchestration.matching import match_step_portfolios
from alertissimo.orchestration.normalization import (
    ExecutionPortfolioResult,
    StepPortfolioResult,
)


def _portfolio(
    *,
    portfolio_id: str,
    execution_id: str,
    broker: str,
    origin: str,
    object_id: str,
    ra: float,
    dec: float,
) -> Portfolio:
    execution = InternalExecutionProvenance(
        internal_execution_id=InternalExecutionId(execution_id),
        broker=broker,
        origin=origin,
        endpoint="objects",
    )
    return Portfolio(
        internal_portfolio_id=InternalPortfolioId(portfolio_id),
        records=(
            SemanticRecord(
                internal_record_id=InternalRecordId(f"record:{portfolio_id}"),
                semantic_type=f"summary@{origin}:{broker}",
                fields={
                    "identity.object_id": object_id,
                    "position.ra": ra,
                    "position.dec": dec,
                },
            ),
        ),
        executions=(execution,),
    )


def test_same_ztf_object_from_two_brokers_harmonizes_before_lsst_ztf_matching():
    fink_ztf = _portfolio(
        portfolio_id="portfolio:fink:ztf",
        execution_id="execution:fink:ztf",
        broker="fink",
        origin="ztf",
        object_id="ZTF20same",
        ra=10.0,
        dec=20.0,
    )
    lasair_ztf = _portfolio(
        portfolio_id="portfolio:lasair:ztf",
        execution_id="execution:lasair:ztf",
        broker="lasair",
        origin="ztf",
        object_id="ZTF20same",
        ra=10.0,
        dec=20.0,
    )
    alerce_lsst = _portfolio(
        portfolio_id="portfolio:alerce:lsst",
        execution_id="execution:alerce:lsst",
        broker="alerce",
        origin="lsst",
        object_id="170000000000000001",
        ra=10.0001,
        dec=20.0,
    )
    source = StepPortfolioResult(
        step_index=0,
        executions=(
            ExecutionPortfolioResult("execution:fink:ztf", (fink_ztf,)),
            ExecutionPortfolioResult("execution:lasair:ztf", (lasair_ztf,)),
            ExecutionPortfolioResult("execution:alerce:lsst", (alerce_lsst,)),
        ),
    )

    # The semantic Step view already treats the two broker observations of the same
    # ZTF identity as one object Portfolio. This is harmonization, not matching.
    assert len(source.portfolios) == 2
    ztf_before = next(
        portfolio
        for portfolio in source.portfolios
        if any(
            record.semantic_type.startswith("summary@ztf:")
            for record in portfolio.records
        )
    )
    assert {execution.broker for execution in ztf_before.executions} == {
        "fink",
        "lasair",
    }
    assert not ztf_before.edges

    matched = match_step_portfolios(
        MatchStep(
            params={
                "candidate_origins": ["lsst", "ztf"],
                "predicate": "position inside 1arcsec",
            }
        ),
        source,
        step_index=1,
    )

    # Matching adds exactly one LSST↔ZTF adjacency relation. It does not create a
    # relation between Fink/ZTF and Lasair/ZTF copies of the same object.
    assert len(matched.portfolios) == 2
    ztf_after = next(
        portfolio
        for portfolio in matched.portfolios
        if any(
            record.semantic_type.startswith("summary@ztf:")
            for record in portfolio.records
        )
    )
    lsst_after = next(
        portfolio
        for portfolio in matched.portfolios
        if any(
            record.semantic_type.startswith("summary@lsst:")
            for record in portfolio.records
        )
    )
    assert {execution.broker for execution in ztf_after.executions} == {
        "fink",
        "lasair",
    }
    assert len(ztf_after.edges) == len(lsst_after.edges) == 1
    assert ztf_after.edges[0].internal_edge_id == lsst_after.edges[0].internal_edge_id
    assert ztf_after.edges[0].edge_type == "--spatially_near--"
    assert lsst_after.edges[0].edge_type == "--spatially_near--"

    # Both execution-local ZTF constituents carry only the redundant projection of
    # that one cross-survey edge; no ZTF↔ZTF identity edge exists.
    ztf_constituents = [
        portfolio
        for execution in matched.executions[:2]
        for portfolio in execution.portfolios
    ]
    assert len(ztf_constituents) == 2
    assert all(len(portfolio.edges) == 1 for portfolio in ztf_constituents)
    assert {
        portfolio.edges[0].internal_edge_id for portfolio in ztf_constituents
    } == {ztf_after.edges[0].internal_edge_id}
