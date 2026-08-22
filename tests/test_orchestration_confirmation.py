import pytest

from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
    InternalPortfolioId,
    InternalRecordId,
    Portfolio,
    SemanticRecord,
)
from alertissimo.orchestration.confirmation import confirm_step_portfolios
from alertissimo.orchestration.ir import ConfirmStep, Source
from alertissimo.orchestration.normalization import (
    ExecutionPortfolioResult,
    StepPortfolioResult,
)


def _portfolio(
    *,
    portfolio_id: str,
    execution_id: str,
    broker: str,
    object_id: str,
    extra_records: int = 0,
) -> Portfolio:
    records = [
        SemanticRecord(
            internal_record_id=InternalRecordId(f"record:{portfolio_id}:summary"),
            semantic_type=f"summary@ztf:{broker}",
            fields={"identity.object_id": object_id},
        )
    ]
    records.extend(
        SemanticRecord(
            internal_record_id=InternalRecordId(f"record:{portfolio_id}:{index}"),
            semantic_type=f"detection@ztf:{broker}",
            fields={"identity.object_id": object_id, "identity.source_id": str(index)},
        )
        for index in range(extra_records)
    )
    return Portfolio(
        internal_portfolio_id=InternalPortfolioId(f"portfolio:{portfolio_id}"),
        records=tuple(records),
        executions=(
            InternalExecutionProvenance(
                internal_execution_id=InternalExecutionId(execution_id),
                broker=broker,
                origin="ztf",
                endpoint="object",
            ),
        ),
    )


def _execution(execution_id: str, portfolio: Portfolio) -> ExecutionPortfolioResult:
    return ExecutionPortfolioResult(execution_id=execution_id, portfolios=(portfolio,))


def test_confirm_ir_quorum_counts_distinct_brokers_not_source_entries():
    with pytest.raises(ValueError, match="distinct explicit broker count"):
        ConfirmStep(
            sources=[
                Source(broker="fink", origin="ztf"),
                Source(broker="fink", origin="lsst"),
            ],
            required_agreement=2,
        )

    step = ConfirmStep(
        sources=[
            Source(broker="fink", origin="ztf"),
            Source(broker="fink", origin="lsst"),
        ],
        required_agreement=1,
    )
    assert step.required_agreement == 1


def test_confirm_counts_distinct_brokers_not_records():
    object_id = "ZTF25aazqavg"
    source = StepPortfolioResult(
        step_index=0,
        executions=(
            _execution(
                "exec:search",
                _portfolio(
                    portfolio_id="search",
                    execution_id="exec:search",
                    broker="alerce",
                    object_id=object_id,
                ),
            ),
        ),
    )
    own = StepPortfolioResult(
        step_index=1,
        executions=(
            _execution(
                "exec:fink",
                _portfolio(
                    portfolio_id="fink",
                    execution_id="exec:fink",
                    broker="fink",
                    object_id=object_id,
                    extra_records=20,
                ),
            ),
            _execution(
                "exec:lasair",
                _portfolio(
                    portfolio_id="lasair",
                    execution_id="exec:lasair",
                    broker="lasair",
                    object_id=object_id,
                ),
            ),
        ),
    )
    step = ConfirmStep(
        sources=[
            Source(broker="fink", origin="ztf"),
            Source(broker="lasair", origin="ztf"),
        ],
        required_agreement=2,
    )

    result = confirm_step_portfolios(step, source, own, step_index=1)

    assert len(result.portfolios) == 1
    assert {execution.broker for execution in result.portfolios[0].executions} == {
        "alerce",
        "fink",
        "lasair",
    }
    assert len(result.executions) == 2


def test_confirm_rejects_candidate_below_quorum_but_keeps_physical_audit_groups():
    object_id = "ZTF25aazqavg"
    source_portfolio = _portfolio(
        portfolio_id="search",
        execution_id="exec:search",
        broker="alerce",
        object_id=object_id,
    )
    source = StepPortfolioResult(
        step_index=0,
        executions=(_execution("exec:search", source_portfolio),),
    )
    fink = _portfolio(
        portfolio_id="fink",
        execution_id="exec:fink",
        broker="fink",
        object_id=object_id,
        extra_records=20,
    )
    own = StepPortfolioResult(
        step_index=1,
        executions=(_execution("exec:fink", fink),),
    )
    step = ConfirmStep(
        sources=[
            Source(broker="fink", origin="ztf"),
            Source(broker="lasair", origin="ztf"),
        ],
        required_agreement=2,
    )

    result = confirm_step_portfolios(step, source, own, step_index=1)

    assert result.portfolios == ()
    assert result.executions == own.executions
