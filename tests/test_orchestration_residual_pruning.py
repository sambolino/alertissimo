"""Tests for applying planner residual predicates after normalization."""

from __future__ import annotations

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
    InternalPortfolioId,
    InternalRecordId,
    Portfolio,
    SemanticRecord,
)
from alertissimo.orchestration.ir import SemanticSearchStep, WorkflowIR
from alertissimo.orchestration.ir.predicates import (
    ComparisonPredicate,
    PredicateLiteral,
    SemanticReference,
)
from alertissimo.orchestration.normalization import (
    normalize_step_execution,
    normalize_workflow_execution,
)
from alertissimo.orchestration.runtime import (
    EndpointPlan,
    PredicateRealization,
    StepExecutionResult,
    StepRun,
    StepRunState,
    WorkflowExecutionResult,
    WorkflowRun,
)


def _summary_predicate(operator: str, value: float) -> ComparisonPredicate:
    return ComparisonPredicate(
        operator=operator,
        left=SemanticReference(
            semantic_type="summary",
            field_path="time.last_mjd",
        ),
        right=PredicateLiteral(value=value),
    )


def _portfolio(name: str, last_mjd: float) -> Portfolio:
    return Portfolio(
        internal_portfolio_id=InternalPortfolioId(name),
        records=(
            SemanticRecord(
                internal_record_id=InternalRecordId(f"record:{name}"),
                semantic_type="summary@ztf:test",
                fields={"time.last_mjd": last_mjd},
            ),
        ),
    )


def _execution(execution_id: str, endpoint: str) -> ExecutionResult:
    return ExecutionResult(
        payload={},
        execution_provenance=InternalExecutionProvenance(
            internal_execution_id=InternalExecutionId(execution_id),
            broker="test",
            origin="ztf",
            endpoint=endpoint,
        ),
    )


def _result(
    plans: tuple[EndpointPlan, ...],
    executions: tuple[ExecutionResult, ...],
) -> WorkflowExecutionResult:
    workflow = WorkflowIR(steps=[SemanticSearchStep(semantic_type="summary")])
    run = WorkflowRun(
        workflow=workflow,
        steps=(
            StepRun(
                step_index=0,
                state=StepRunState.SUCCEEDED,
                endpoint_plans=plans,
                execution_ids=tuple(
                    execution.internal_execution_id.value for execution in executions
                ),
            ),
        ),
    )
    return WorkflowExecutionResult(
        run=run,
        steps=(StepExecutionResult(step_index=0, executions=executions),),
    )


def test_workflow_normalization_applies_residual_per_aligned_execution(monkeypatch):
    first_execution = _execution("execution:first", "first")
    second_execution = _execution("execution:second", "second")
    first_plan = EndpointPlan(
        broker="test",
        origin="ztf",
        endpoint="first",
        predicate_realization=PredicateRealization(
            residual=_summary_predicate(">", 60000.0)
        ),
    )
    second_plan = EndpointPlan(
        broker="test",
        origin="ztf",
        endpoint="second",
        predicate_realization=PredicateRealization(
            residual=_summary_predicate("<", 59000.0)
        ),
    )
    normalized = {
        "execution:first": (
            _portfolio("first-old", 58000.0),
            _portfolio("first-new", 61000.0),
        ),
        "execution:second": (
            _portfolio("second-old", 58000.0),
            _portfolio("second-new", 61000.0),
        ),
    }

    def fake_normalize(execution, *, validate_semantic_model=True):
        return normalized[execution.internal_execution_id.value]

    monkeypatch.setattr(
        "alertissimo.orchestration.normalization.normalize.normalize_execution",
        fake_normalize,
    )

    result = normalize_workflow_execution(
        _result(
            (first_plan, second_plan),
            (first_execution, second_execution),
        )
    )

    outputs = result.steps[0].executions
    assert [
        portfolio.internal_portfolio_id.value for portfolio in outputs[0].portfolios
    ] == ["first-new"]
    assert [
        portfolio.internal_portfolio_id.value for portfolio in outputs[1].portfolios
    ] == ["second-old"]
    assert result.run.steps[0].endpoint_plans[0].predicate_realization.residual is not None
    assert result.run.steps[0].endpoint_plans[1].predicate_realization.residual is not None


def test_pushdown_only_realization_does_not_recheck_or_prune(monkeypatch):
    execution = _execution("execution:pushdown", "pushdown")
    predicate = _summary_predicate(">", 60000.0)
    plan = EndpointPlan(
        broker="test",
        origin="ztf",
        endpoint="pushdown",
        predicate_realization=PredicateRealization(
            pushdown=predicate,
            params={"server_limit": 60000.0},
        ),
    )
    portfolios = (
        _portfolio("provider-returned-a", 58000.0),
        _portfolio("provider-returned-b", 61000.0),
    )

    monkeypatch.setattr(
        "alertissimo.orchestration.normalization.normalize.normalize_execution",
        lambda execution, *, validate_semantic_model=True: portfolios,
    )

    result = normalize_workflow_execution(_result((plan,), (execution,)))

    assert result.steps[0].executions[0].portfolios == portfolios


def test_standalone_step_normalization_remains_strategy_free(monkeypatch):
    execution = _execution("execution:standalone", "standalone")
    portfolios = (
        _portfolio("standalone-old", 58000.0),
        _portfolio("standalone-new", 61000.0),
    )

    monkeypatch.setattr(
        "alertissimo.orchestration.normalization.normalize.normalize_execution",
        lambda execution, *, validate_semantic_model=True: portfolios,
    )

    result = normalize_step_execution(
        StepExecutionResult(step_index=3, executions=(execution,))
    )

    assert result.executions[0].portfolios == portfolios
