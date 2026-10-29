"""Physical execution reuse must preserve normalized Portfolio identity."""

from __future__ import annotations

import pytest

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
from alertissimo.orchestration.normalization import WorkflowNormalizationAlignmentError, normalize_workflow_execution
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


def _fanout_result(consumer_order):
    owner = EndpointPlan(broker="generic", origin="survey", endpoint="history")
    consumer = owner.model_copy(update={"execution_reuse_from": EndpointPlanRef(step_index=0, plan_index=0)})
    executions = tuple(ExecutionResult(payload={}, execution_provenance=InternalExecutionProvenance(
        InternalExecutionId(f"execution:fanout:{index}"), "generic", "survey", "history",
    )) for index in range(4))
    consumed = tuple(executions[index] for index in consumer_order)
    owner_executions = executions[:3]
    run = WorkflowRun(workflow=WorkflowIR(steps=[SemanticSearchStep(semantic_type="summary"), GetClassificationStep()]), steps=(
        StepRun(step_index=0, state=StepRunState.SUCCEEDED, endpoint_plans=(owner,),
                execution_ids=tuple(item.internal_execution_id.value for item in owner_executions), execution_plan_indexes=(0, 0, 0)),
        StepRun(step_index=1, state=StepRunState.SUCCEEDED, endpoint_plans=(consumer,),
                execution_ids=tuple(item.internal_execution_id.value for item in consumed), execution_plan_indexes=(0,) * len(consumed)),
    ))
    return WorkflowExecutionResult(run=run, steps=(StepExecutionResult(0, owner_executions), StepExecutionResult(1, consumed)))


def test_fanout_reuse_normalizes_each_owner_execution_once(monkeypatch):
    result = _fanout_result((0, 1, 2))
    calls = []
    def normalize_once(execution, *, validate_semantic_model=True):
        calls.append(execution.internal_execution_id.value)
        return (Portfolio(internal_portfolio_id=InternalPortfolioId("portfolio:" + execution.internal_execution_id.value)),)
    monkeypatch.setattr("alertissimo.orchestration.normalization.normalize.normalize_execution", normalize_once)
    normalized = normalize_workflow_execution(result)
    assert calls == [f"execution:fanout:{index}" for index in range(3)]
    assert all(owner.portfolios[0] is consumer.portfolios[0]
               for owner, consumer in zip(normalized.steps[0].executions, normalized.steps[1].executions))


@pytest.mark.parametrize("order", [(1, 0, 2), (0, 0, 2), (0, 2), (0, 1, 3)],
                         ids=["reordered", "duplicated", "missing", "foreign"])
def test_reused_fanout_must_preserve_the_entire_ordered_owner_group(monkeypatch, order):
    def unexpected(*args, **kwargs):
        raise AssertionError("misaligned reuse must fail before normalization")
    monkeypatch.setattr("alertissimo.orchestration.normalization.normalize.normalize_execution", unexpected)
    with pytest.raises(WorkflowNormalizationAlignmentError, match="declared reuse owner"):
        normalize_workflow_execution(_fanout_result(order))
