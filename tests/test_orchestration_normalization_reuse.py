"""Physical execution reuse must preserve normalized Portfolio identity."""

from __future__ import annotations

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
    InternalPortfolioId,
    Portfolio,
)
from alertissimo.orchestration.ir import (
    GetClassificationStep,
    SemanticSearchStep,
    WorkflowIR,
)
from alertissimo.orchestration.normalization import normalize_workflow_execution
from alertissimo.orchestration.runtime import (
    EndpointPlan,
    EndpointPlanRef,
    StepExecutionResult,
    StepRun,
    StepRunState,
    WorkflowExecutionResult,
    WorkflowRun,
)


def test_reused_physical_execution_is_normalized_once_and_shares_portfolio(monkeypatch):
    workflow = WorkflowIR(
        steps=[
            SemanticSearchStep(semantic_type="summary"),
            GetClassificationStep(),
        ]
    )
    owner_plan = EndpointPlan(
        broker="generic",
        origin="survey",
        endpoint="search",
    )
    consumer_plan = EndpointPlan(
        broker="generic",
        origin="survey",
        endpoint="search",
        execution_reuse_from=EndpointPlanRef(step_index=0, plan_index=0),
    )
    run = WorkflowRun(
        workflow=workflow,
        steps=(
            StepRun(
                step_index=0,
                state=StepRunState.SUCCEEDED,
                endpoint_plans=(owner_plan,),
                execution_ids=("execution:shared",),
            ),
            StepRun(
                step_index=1,
                state=StepRunState.SUCCEEDED,
                endpoint_plans=(consumer_plan,),
                execution_ids=("execution:shared",),
            ),
        ),
    )
    shared_execution = ExecutionResult(
        payload={},
        execution_provenance=InternalExecutionProvenance(
            internal_execution_id=InternalExecutionId("execution:shared"),
            broker="generic",
            origin="survey",
            endpoint="search",
        ),
    )
    execution_result = WorkflowExecutionResult(
        run=run,
        steps=(
            StepExecutionResult(step_index=0, executions=(shared_execution,)),
            StepExecutionResult(step_index=1, executions=(shared_execution,)),
        ),
    )
    portfolio = Portfolio(
        internal_portfolio_id=InternalPortfolioId("portfolio:shared"),
    )
    calls = 0

    def normalize_once(execution, *, validate_semantic_model=True):
        nonlocal calls
        calls += 1
        assert execution is shared_execution
        return (portfolio,)

    monkeypatch.setattr(
        "alertissimo.orchestration.normalization.normalize.normalize_execution",
        normalize_once,
    )

    normalized = normalize_workflow_execution(execution_result)

    assert calls == 1
    owner_portfolio = normalized.steps[0].executions[0].portfolios[0]
    consumer_portfolio = normalized.steps[1].executions[0].portfolios[0]
    assert owner_portfolio is portfolio
    assert consumer_portfolio is portfolio
    assert owner_portfolio is consumer_portfolio
