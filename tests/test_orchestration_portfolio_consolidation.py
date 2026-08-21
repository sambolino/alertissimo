"""Step-level semantic Portfolio consolidation across physical executions."""

from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
    InternalPortfolioId,
    InternalRecordId,
    InternalRecordSource,
    Portfolio,
    SemanticRecord,
)
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
    marker: str,
) -> Portfolio:
    execution = InternalExecutionProvenance(
        internal_execution_id=InternalExecutionId(execution_id),
        broker=broker,
        origin=origin,
        endpoint=marker,
    )
    summary = SemanticRecord(
        internal_record_id=InternalRecordId(f"record:{marker}:summary"),
        semantic_type=f"summary@{origin}:{broker}",
        fields={"identity.object_id": object_id},
    )
    detection = SemanticRecord(
        internal_record_id=InternalRecordId(f"record:{marker}:detection"),
        semantic_type=f"detection@{origin}:{broker}",
        fields={"identity.object_id": object_id, "measurement.marker": marker},
        internal_source=InternalRecordSource(
            internal_execution_id=execution.internal_execution_id,
            payload_key=marker,
            payload_path="[]",
            payload_index=0,
        ),
    )
    return Portfolio(
        internal_portfolio_id=InternalPortfolioId(portfolio_id),
        records=(summary, detection),
        executions=(execution,),
    )


def _execution(execution_id: str, *portfolios: Portfolio) -> ExecutionPortfolioResult:
    return ExecutionPortfolioResult(execution_id=execution_id, portfolios=portfolios)


def test_same_origin_and_object_id_merge_across_executions_with_full_provenance():
    sources = _portfolio(
        portfolio_id="portfolio:sources:A",
        execution_id="execution:sources",
        broker="fink",
        origin="lsst",
        object_id="1701",
        marker="sources",
    )
    forced = _portfolio(
        portfolio_id="portfolio:fp:A",
        execution_id="execution:fp",
        broker="fink",
        origin="lsst",
        object_id="1701",
        marker="fp",
    )
    step = StepPortfolioResult(
        step_index=2,
        executions=(
            _execution("execution:sources", sources),
            _execution("execution:fp", forced),
        ),
    )

    assert len(step.executions) == 2
    assert step.executions[0].portfolios == (sources,)
    assert step.executions[1].portfolios == (forced,)

    first_view = step.portfolios
    assert step.portfolios is first_view  # cached semantic view, stable merged ID
    assert len(first_view) == 1
    merged = first_view[0]
    assert merged is not sources and merged is not forced
    assert merged.internal_portfolio_id not in {
        sources.internal_portfolio_id,
        forced.internal_portfolio_id,
    }
    assert [record.internal_record_id.value for record in merged.records] == [
        "record:sources:summary",
        "record:sources:detection",
        "record:fp:summary",
        "record:fp:detection",
    ]
    assert [execution.internal_execution_id.value for execution in merged.executions] == [
        "execution:sources",
        "execution:fp",
    ]
    assert {
        record.internal_source.internal_execution_id.value
        for record in merged.records
        if record.internal_source is not None
    } == {"execution:sources", "execution:fp"}


def test_step_semantic_view_merges_by_identity_and_preserves_first_object_order():
    source_a = _portfolio(
        portfolio_id="portfolio:sources:A",
        execution_id="execution:sources",
        broker="fink",
        origin="lsst",
        object_id="A",
        marker="sources-A",
    )
    source_b = _portfolio(
        portfolio_id="portfolio:sources:B",
        execution_id="execution:sources",
        broker="fink",
        origin="lsst",
        object_id="B",
        marker="sources-B",
    )
    forced_a = _portfolio(
        portfolio_id="portfolio:fp:A",
        execution_id="execution:fp",
        broker="fink",
        origin="lsst",
        object_id="A",
        marker="fp-A",
    )
    step = StepPortfolioResult(
        step_index=0,
        executions=(
            _execution("execution:sources", source_a, source_b),
            _execution("execution:fp", forced_a),
        ),
    )

    assert len(step.portfolios) == 2
    merged_a, singleton_b = step.portfolios
    assert singleton_b is source_b
    assert [execution.internal_execution_id.value for execution in merged_a.executions] == [
        "execution:sources",
        "execution:fp",
    ]
    identities = [
        {
            str(record.get("identity.object_id"))
            for record in portfolio.records
            if record.semantic_type.startswith("summary@")
            and record.get("identity.object_id") is not None
        }
        for portfolio in step.portfolios
    ]
    assert identities == [{"A"}, {"B"}]


def test_same_bare_object_id_from_different_origins_never_merges():
    lsst = _portfolio(
        portfolio_id="portfolio:lsst",
        execution_id="execution:lsst",
        broker="fink",
        origin="lsst",
        object_id="123",
        marker="lsst",
    )
    ztf = _portfolio(
        portfolio_id="portfolio:ztf",
        execution_id="execution:ztf",
        broker="fink",
        origin="ztf",
        object_id="123",
        marker="ztf",
    )
    step = StepPortfolioResult(
        step_index=0,
        executions=(
            _execution("execution:lsst", lsst),
            _execution("execution:ztf", ztf),
        ),
    )

    assert step.portfolios == (lsst, ztf)


def test_same_origin_and_object_id_can_merge_across_brokers():
    fink = _portfolio(
        portfolio_id="portfolio:fink",
        execution_id="execution:fink",
        broker="fink",
        origin="ztf",
        object_id="ZTF20abc",
        marker="fink",
    )
    lasair = _portfolio(
        portfolio_id="portfolio:lasair",
        execution_id="execution:lasair",
        broker="lasair",
        origin="ztf",
        object_id="ZTF20abc",
        marker="lasair",
    )
    step = StepPortfolioResult(
        step_index=0,
        executions=(
            _execution("execution:fink", fink),
            _execution("execution:lasair", lasair),
        ),
    )

    assert len(step.portfolios) == 1
    assert [execution.broker for execution in step.portfolios[0].executions] == [
        "fink",
        "lasair",
    ]


def test_unidentified_or_ambiguous_portfolio_remains_independent():
    known = _portfolio(
        portfolio_id="portfolio:known",
        execution_id="execution:known",
        broker="fink",
        origin="lsst",
        object_id="A",
        marker="known",
    )
    ambiguous = Portfolio(
        internal_portfolio_id=InternalPortfolioId("portfolio:ambiguous"),
        records=(
            SemanticRecord(
                InternalRecordId("record:ambiguous:a"),
                "summary@lsst:fink",
                {"identity.object_id": "A"},
            ),
            SemanticRecord(
                InternalRecordId("record:ambiguous:b"),
                "summary@lsst:fink",
                {"identity.object_id": "B"},
            ),
        ),
    )
    unidentified = Portfolio(
        internal_portfolio_id=InternalPortfolioId("portfolio:unidentified"),
        records=(
            SemanticRecord(
                InternalRecordId("record:no-id"),
                "detection@lsst:fink",
                {"identity.object_id": "A"},
            ),
        ),
    )
    step = StepPortfolioResult(
        step_index=0,
        executions=(
            _execution("execution:known", known),
            _execution("execution:ambiguous", ambiguous),
            _execution("execution:unidentified", unidentified),
        ),
    )

    assert step.portfolios == (known, ambiguous, unidentified)


def test_repeated_reference_to_same_canonical_portfolio_is_not_rewrapped():
    portfolio = _portfolio(
        portfolio_id="portfolio:shared",
        execution_id="execution:shared",
        broker="alerce",
        origin="lsst",
        object_id="1701",
        marker="shared",
    )
    step = StepPortfolioResult(
        step_index=0,
        executions=(
            _execution("execution:shared", portfolio),
            _execution("execution:shared", portfolio),
        ),
    )

    assert step.portfolios == (portfolio,)
    assert step.portfolios[0] is portfolio
