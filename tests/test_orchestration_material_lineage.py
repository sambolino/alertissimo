"""Contracts for immutable semantic material lineage across workflow Steps."""

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
    consolidate_portfolios,
)


def _portfolio(
    *,
    name: str,
    origin: str,
    object_id: str,
    broker: str,
    endpoint: str,
    position: tuple[float, float] | None = None,
) -> Portfolio:
    execution = InternalExecutionProvenance(
        internal_execution_id=InternalExecutionId(f"execution:{name}"),
        broker=broker,
        origin=origin,
        endpoint=endpoint,
    )
    fields = {"identity.object_id": object_id}
    if position is not None:
        fields.update({"position.ra": position[0], "position.dec": position[1]})
    return Portfolio(
        internal_portfolio_id=InternalPortfolioId(f"portfolio:{name}"),
        records=(
            SemanticRecord(
                internal_record_id=InternalRecordId(f"record:{name}"),
                semantic_type=f"summary@{origin}:{broker}",
                fields=fields,
            ),
        ),
        executions=(execution,),
    )


def _execution(portfolio: Portfolio) -> ExecutionPortfolioResult:
    return ExecutionPortfolioResult(
        execution_id=portfolio.executions[0].internal_execution_id.value,
        portfolios=(portfolio,),
    )


def test_materialized_snapshot_accumulates_semantics_but_not_step_physical_ownership():
    search = _portfolio(
        name="search",
        origin="ztf",
        object_id="ZTF1",
        broker="lasair",
        endpoint="cone",
        position=(10.0, 20.0),
    )
    enrichment = _portfolio(
        name="enrichment",
        origin="ztf",
        object_id="ZTF1",
        broker="fink",
        endpoint="objects",
    )
    search_view = StepPortfolioResult(step_index=0, executions=(_execution(search),))
    enrichment_own = StepPortfolioResult(
        step_index=1,
        executions=(_execution(enrichment),),
    )
    enrichment_view = StepPortfolioResult(
        step_index=1,
        executions=enrichment_own.executions,
        materialized_portfolios=consolidate_portfolios(
            search_view.portfolios + enrichment_own.portfolios
        ),
    )

    assert enrichment_view.executions == enrichment_own.executions
    assert len(enrichment_view.portfolios) == 1
    semantic = enrichment_view.portfolios[0]
    assert {
        (execution.broker, execution.endpoint)
        for execution in semantic.executions
    } == {("lasair", "cone"), ("fink", "objects")}
    assert search_view.portfolios == (search,)


def test_match_can_use_position_inherited_before_immediately_preceding_get():
    lsst_search = _portfolio(
        name="lsst-search",
        origin="lsst",
        object_id="LSST1",
        broker="alerce",
        endpoint="query_objects",
        position=(10.0, 20.0),
    )
    ztf_search = _portfolio(
        name="ztf-search",
        origin="ztf",
        object_id="ZTF1",
        broker="alerce",
        endpoint="query_objects",
        position=(10.0001, 20.0),
    )
    # The immediately preceding Get output deliberately contains identity only. If
    # Match inspects only this Step's own physical executions, position matching is
    # impossible. The materialized snapshot must carry the earlier Search position.
    lsst_get = _portfolio(
        name="lsst-get",
        origin="lsst",
        object_id="LSST1",
        broker="fink",
        endpoint="sources",
    )
    ztf_get = _portfolio(
        name="ztf-get",
        origin="ztf",
        object_id="ZTF1",
        broker="fink",
        endpoint="objects",
    )
    source = StepPortfolioResult(
        step_index=1,
        executions=(_execution(lsst_get), _execution(ztf_get)),
        materialized_portfolios=consolidate_portfolios(
            (lsst_search, ztf_search, lsst_get, ztf_get)
        ),
    )

    matched = match_step_portfolios(
        MatchStep(
            params={
                "candidate_origins": ["lsst", "ztf"],
                "predicate": "position inside 1arcsec",
            }
        ),
        source,
        step_index=2,
    )

    assert matched.executions == ()
    assert len(matched.portfolios) == 2
    assert all(len(portfolio.edges) == 1 for portfolio in matched.portfolios)
    assert {
        record.get("identity.object_id")
        for portfolio in matched.portfolios
        for record in portfolio.records
        if record.semantic_type.startswith("summary@")
    } == {"LSST1", "ZTF1"}
