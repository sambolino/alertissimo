"""Execution coalescing without collapsing semantic WorkflowIR Steps."""

from __future__ import annotations

from alertissimo.data_layer.execution import EndpointRegistry, ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
    InternalPortfolioId,
    InternalRecordId,
    Portfolio,
    SemanticRecord,
)
from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraph,
    EndpointCapability,
    SemanticRecordCapability,
    build_capability_graph,
)
from alertissimo.orchestration.binding import bind_workflow_run
from alertissimo.orchestration.ir import (
    ComparisonPredicate,
    GetClassificationStep,
    PredicateLiteral,
    SemanticReference,
    SemanticSearchStep,
    Source,
    WorkflowIR,
    and_predicates,
)
from alertissimo.orchestration.normalization import (
    WorkflowNormalizationAlignmentError,
    normalize_workflow_execution,
)
from alertissimo.orchestration.planner import PlanningDeferredError, plan_workflow
from alertissimo.orchestration.runtime import (
    EndpointPlan,
    EndpointPlanRef,
    PredicateRealization,
    StepExecutionResult,
    StepRun,
    StepRunState,
    WorkflowExecutionResult,
    WorkflowRun,
    execute_workflow_run,
)


def _classification_predicate(
    *,
    producer: str = "lc_classifier",
    channel: str | None = "alerce",
):
    return and_predicates(
        [
            ComparisonPredicate(
                left=SemanticReference(
                    semantic_type="classification",
                    producer=producer,
                    channel=channel,
                    field_path="best.class",
                ),
                operator="=",
                right=PredicateLiteral(value="SN"),
            ),
            ComparisonPredicate(
                left=SemanticReference(
                    semantic_type="classification",
                    producer=producer,
                    channel=channel,
                    field_path="best.probability",
                ),
                operator=">=",
                right=PredicateLiteral(value=0.8),
            ),
        ]
    )


def test_alerce_search_and_classification_keep_two_steps_but_execute_once():
    """The motivating case proves reuse without becoming a planner special case."""

    workflow = WorkflowIR(
        steps=[
            SemanticSearchStep(
                semantic_type="summary",
                predicate=_classification_predicate(),
                sources=[Source(broker="alerce", origin="lsst")],
            ),
            GetClassificationStep(
                classifier="lc_classifier",
                sources=[Source(broker="alerce", origin="lsst")],
            ),
        ]
    )
    graph = build_capability_graph()
    run = plan_workflow(workflow, graph)

    assert len(run.workflow.steps) == 2
    assert run.workflow.steps[0].op == "semantic_search"
    assert run.workflow.steps[1].op == "get_classification"

    search_plan = run.steps[0].endpoint_plans[0]
    classification_plan = run.steps[1].endpoint_plans[0]
    assert (
        search_plan.broker,
        search_plan.origin,
        search_plan.endpoint,
    ) == ("alerce", "lsst", "query_objects")
    assert (
        classification_plan.broker,
        classification_plan.origin,
        classification_plan.endpoint,
    ) == ("alerce", "lsst", "query_objects")
    assert classification_plan.execution_reuse_from == EndpointPlanRef(
        step_index=0, plan_index=0
    )
    assert search_plan.predicate_realization is not None
    assert search_plan.predicate_realization.params == {
        "classifier": "lc_classifier",
        "class_name": "SN",
        "probability": 0.8,
    }

    bindings = bind_workflow_run(run, EndpointRegistry())
    assert bindings[0].bound_calls[0].params == {
        "classifier": "lc_classifier",
        "class_name": "SN",
        "probability": 0.8,
    }
    assert bindings[1].bound_calls[0].params == {}

    class CountingExecutor:
        def __init__(self):
            self.calls = []

        def execute(self, *, broker, origin, endpoint, params):
            self.calls.append((broker, origin, endpoint, dict(params)))
            return ExecutionResult(
                payload=[],
                execution_provenance=InternalExecutionProvenance(
                    internal_execution_id=InternalExecutionId("execution:shared"),
                    broker=broker,
                    origin=origin,
                    endpoint=endpoint,
                    params=params,
                ),
            )

    executor = CountingExecutor()
    executed = execute_workflow_run(run, bindings, executor)

    assert len(executor.calls) == 1
    assert executor.calls[0][0:3] == ("alerce", "lsst", "query_objects")
    assert [
        step.executions[0].internal_execution_id.value for step in executed.steps
    ] == ["execution:shared", "execution:shared"]
    assert [
        step.execution_ids for step in executed.run.steps
    ] == [("execution:shared",), ("execution:shared",)]


def test_dynamic_producer_is_not_assumed_without_positive_search_requirement():
    """A provider default classifier is never invented as a reuse guarantee."""

    workflow = WorkflowIR(
        steps=[
            SemanticSearchStep(
                semantic_type="summary",
                sources=[Source(broker="alerce", origin="lsst")],
            ),
            GetClassificationStep(
                classifier="lc_classifier",
                sources=[Source(broker="alerce", origin="lsst")],
            ),
        ]
    )

    import pytest

    with pytest.raises(
        PlanningDeferredError,
        match="candidate enrichment requires runtime binding",
    ):
        plan_workflow(workflow, build_capability_graph())


def test_coalescing_proof_is_provider_neutral():
    """A synthetic provider uses the same semantic proof with no broker branch."""

    endpoint = EndpointCapability(
        broker="generic",
        origin="survey",
        endpoint="search",
        path="search",
        method="search",
        operation_types=("object_search",),
        params=("classifier",),
        server_filters=("classifier",),
        projection_param=None,
        supports_projection=False,
        output_type="array",
    )
    graph = CapabilityGraph(
        endpoint_capabilities=(endpoint,),
        payload_capabilities=(),
        field_mapping_capabilities=(),
        transform_capabilities=(),
        semantic_record_capabilities=(
            SemanticRecordCapability(
                broker="generic",
                origin="survey",
                semantic_record_type="summary@survey:generic",
                endpoints=("search",),
                fields=(),
            ),
            SemanticRecordCapability(
                broker="generic",
                origin="survey",
                semantic_record_type="classification@{producer}:generic",
                endpoints=("search",),
                fields=("best.class",),
            ),
        ),
    )
    predicate = ComparisonPredicate(
        left=SemanticReference(
            semantic_type="classification",
            producer="model_x",
            field_path="best.class",
        ),
        operator="=",
        right=PredicateLiteral(value="SN"),
    )
    workflow = WorkflowIR(
        steps=[
            SemanticSearchStep(
                semantic_type="summary",
                predicate=predicate,
                sources=[Source(broker="generic", origin="survey")],
            ),
            GetClassificationStep(
                classifier="model_x",
                sources=[Source(broker="generic", origin="survey")],
            ),
        ]
    )

    run = plan_workflow(workflow, graph)

    assert run.steps[1].endpoint_plans[0].execution_reuse_from == EndpointPlanRef(
        step_index=0, plan_index=0
    )


def _summary_residual():
    return ComparisonPredicate(
        left=SemanticReference(
            semantic_type="summary",
            field_path="time.last_mjd",
        ),
        operator=">",
        right=PredicateLiteral(value=60000.0),
    )


def _portfolio(name: str, last_mjd: float) -> Portfolio:
    return Portfolio(
        internal_portfolio_id=InternalPortfolioId(name),
        records=(
            SemanticRecord(
                internal_record_id=InternalRecordId(f"record:{name}"),
                semantic_type="summary@survey:generic",
                fields={"time.last_mjd": last_mjd},
            ),
        ),
    )


def test_reused_step_inherits_owner_residual_during_normalization(monkeypatch):
    """Shared raw execution must not resurrect candidates pruned by its owner."""

    workflow = WorkflowIR(
        steps=[
            SemanticSearchStep(semantic_type="summary"),
            GetClassificationStep(),
        ]
    )
    residual = _summary_residual()
    owner_plan = EndpointPlan(
        broker="generic",
        origin="survey",
        endpoint="search",
        predicate_realization=PredicateRealization(residual=residual),
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
    shared = ExecutionResult(
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
            StepExecutionResult(step_index=0, executions=(shared,)),
            StepExecutionResult(step_index=1, executions=(shared,)),
        ),
    )
    portfolios = (
        _portfolio("old", 59000.0),
        _portfolio("new", 61000.0),
    )

    monkeypatch.setattr(
        "alertissimo.orchestration.normalization.normalize.normalize_execution",
        lambda execution, *, validate_semantic_model=True: portfolios,
    )

    normalized = normalize_workflow_execution(execution_result)

    assert [
        portfolio.internal_portfolio_id.value
        for portfolio in normalized.steps[0].executions[0].portfolios
    ] == ["new"]
    assert [
        portfolio.internal_portfolio_id.value
        for portfolio in normalized.steps[1].executions[0].portfolios
    ] == ["new"]


def test_reused_execution_id_mismatch_is_rejected_before_normalization(monkeypatch):
    workflow = WorkflowIR(
        steps=[
            SemanticSearchStep(semantic_type="summary"),
            GetClassificationStep(),
        ]
    )
    owner_plan = EndpointPlan(broker="generic", origin="survey", endpoint="search")
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
                execution_ids=("execution:owner",),
            ),
            StepRun(
                step_index=1,
                state=StepRunState.SUCCEEDED,
                endpoint_plans=(consumer_plan,),
                execution_ids=("execution:wrong",),
            ),
        ),
    )
    owner_execution = ExecutionResult(
        payload={},
        execution_provenance=InternalExecutionProvenance(
            InternalExecutionId("execution:owner"),
            "generic",
            "survey",
            "search",
        ),
    )
    wrong_execution = ExecutionResult(
        payload={},
        execution_provenance=InternalExecutionProvenance(
            InternalExecutionId("execution:wrong"),
            "generic",
            "survey",
            "search",
        ),
    )
    result = WorkflowExecutionResult(
        run=run,
        steps=(
            StepExecutionResult(step_index=0, executions=(owner_execution,)),
            StepExecutionResult(step_index=1, executions=(wrong_execution,)),
        ),
    )
    called = False

    def unexpected(*args, **kwargs):
        nonlocal called
        called = True
        return ()

    monkeypatch.setattr(
        "alertissimo.orchestration.normalization.normalize.normalize_execution",
        unexpected,
    )

    import pytest

    with pytest.raises(
        WorkflowNormalizationAlignmentError, match="declared reuse owner"
    ):
        normalize_workflow_execution(result)
    assert called is False
