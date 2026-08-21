"""Focused tests for minimal workflow invocation state."""

from itertools import count

import pytest
from pydantic import ValidationError

from alertissimo.data_layer.execution import EndpointRegistry, ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
    InternalPortfolioId,
    InternalRecordId,
    Portfolio,
    SemanticRecord,
)
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.orchestration.ir import TargetSelector
from alertissimo.orchestration.ir.models import (
    ConeSearchStep,
    FilterStep,
    GetLightcurveStep,
    Source,
    WorkflowIR,
)
from alertissimo.orchestration.pipeline import execute_staged_workflow_run
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import (
    CandidateInputRef,
    EndpointPlan,
    StepRun,
    StepRunState,
    WorkflowRun,
)


def _repeated_workflow() -> WorkflowIR:
    source = [Source(broker="lasair", origin="ztf")]
    return WorkflowIR(
        steps=[
            GetLightcurveStep(target=TargetSelector(ids=["A"], kind="object"), sources=source),
            GetLightcurveStep(target=TargetSelector(ids=["B"], kind="object"), sources=source),
        ]
    )


def test_from_workflow_creates_ordered_pending_step_runs():
    workflow = _repeated_workflow()
    run = WorkflowRun.from_workflow(workflow)

    assert [step.step_index for step in run.steps] == [0, 1]
    assert all(step.state is StepRunState.PENDING for step in run.steps)
    assert all(step.endpoint_plans == () for step in run.steps)
    assert run.step_at(1).target.ids == ["B"]
    assert run.step_run_at(0) is run.steps[0]


@pytest.mark.parametrize(
    "steps",
    [
        (StepRun(step_index=0),),
        (StepRun(step_index=0), StepRun(step_index=0)),
        (StepRun(step_index=1), StepRun(step_index=0)),
    ],
)
def test_workflow_run_rejects_missing_duplicate_or_out_of_order_indices(steps):
    with pytest.raises(ValidationError, match="indices must cover"):
        WorkflowRun(workflow=_repeated_workflow(), steps=steps)


def test_step_run_rejects_negative_index():
    with pytest.raises(ValidationError):
        StepRun(step_index=-1)


def test_same_operation_steps_remain_distinct_after_planning():
    run = plan_workflow(_repeated_workflow(), build_capability_graph())

    assert [step.step_index for step in run.steps] == [0, 1]
    assert [run.step_at(step.step_index).target.ids[0] for step in run.steps] == ["A", "B"]
    assert all(step.state is StepRunState.PLANNED for step in run.steps)
    assert [step.endpoint_plans[0].endpoint for step in run.steps] == [
        "lightcurves",
        "lightcurves",
    ]
    assert run.steps[0].endpoint_plans is not run.steps[1].endpoint_plans
    assert all(
        not hasattr(plan, "target_id") and not hasattr(plan, "step_op")
        for step in run.steps
        for plan in step.endpoint_plans
    )


def test_workflow_run_json_round_trip_preserves_discriminated_steps():
    run = plan_workflow(_repeated_workflow(), build_capability_graph())

    restored = WorkflowRun.model_validate_json(run.model_dump_json())

    assert restored == run
    assert isinstance(restored.workflow.steps[0], GetLightcurveStep)


class _OriginRoutingExecutor:
    def __init__(self, candidate_ids_by_origin):
        self.candidate_ids_by_origin = candidate_ids_by_origin
        self.calls: list[tuple[str, str, str, dict]] = []
        self._ids = count(1)

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        del headers
        params = dict(params or {})
        self.calls.append((broker, origin, endpoint, params))
        payload = {}
        if endpoint == "conesearch":
            payload = {
                "candidate_ids": tuple(self.candidate_ids_by_origin.get(origin, ()))
            }
        execution_id = InternalExecutionId(f"execution:routing:{next(self._ids)}")
        return ExecutionResult(
            payload=payload,
            execution_provenance=InternalExecutionProvenance(
                internal_execution_id=execution_id,
                broker=broker,
                origin=origin,
                endpoint=endpoint,
                params=params,
            ),
        )


def _candidate_portfolio(execution: ExecutionResult, object_id: str) -> Portfolio:
    provenance = execution.execution_provenance
    suffix = f"{provenance.origin}:{object_id}"
    return Portfolio(
        internal_portfolio_id=InternalPortfolioId(f"portfolio:{suffix}"),
        records=(
            SemanticRecord(
                internal_record_id=InternalRecordId(f"record:{suffix}"),
                semantic_type=f"summary@{provenance.origin}:fixture",
                fields={"identity.object_id": object_id},
            ),
        ),
        executions=(provenance,),
    )


def _install_origin_routing_normalization(monkeypatch):
    def fake_normalize(execution, *, validate_semantic_model=True):
        del validate_semantic_model
        return tuple(
            _candidate_portfolio(execution, object_id)
            for object_id in execution.payload.get("candidate_ids", ())
        )

    monkeypatch.setattr(
        "alertissimo.orchestration.pipeline.normalize_execution", fake_normalize
    )
    monkeypatch.setattr(
        "alertissimo.orchestration.pipeline.normalize_workflow_execution",
        lambda execution_result, *, validate_semantic_model=True: None,
    )


def _origin_routing_run(*, through_filter: bool = False) -> WorkflowRun:
    search = ConeSearchStep(
        semantic_type="summary",
        ra=124.87996115142856,
        dec=-6.0205001,
        radius=300.0,
    )
    get = GetLightcurveStep()
    search_plans = (
        EndpointPlan(broker="fink", origin="lsst", endpoint="conesearch"),
        EndpointPlan(broker="fink", origin="ztf", endpoint="conesearch"),
    )
    if through_filter:
        workflow = WorkflowIR(steps=(search, FilterStep(), get))
        source_ref = CandidateInputRef(step_index=1)
        return WorkflowRun(
            workflow=workflow,
            steps=(
                StepRun(
                    step_index=0,
                    state=StepRunState.PLANNED,
                    endpoint_plans=search_plans,
                ),
                StepRun(
                    step_index=1,
                    state=StepRunState.PLANNED,
                    candidate_input_from=CandidateInputRef(step_index=0),
                ),
                StepRun(
                    step_index=2,
                    state=StepRunState.PLANNED,
                    endpoint_plans=(
                        EndpointPlan(
                            broker="fink",
                            origin="lsst",
                            endpoint="sources",
                            candidate_input_from=source_ref,
                        ),
                        EndpointPlan(
                            broker="fink",
                            origin="ztf",
                            endpoint="objects",
                            candidate_input_from=source_ref,
                        ),
                    ),
                ),
            ),
        )

    workflow = WorkflowIR(steps=(search, get))
    source_ref = CandidateInputRef(step_index=0)
    return WorkflowRun(
        workflow=workflow,
        steps=(
            StepRun(
                step_index=0,
                state=StepRunState.PLANNED,
                endpoint_plans=search_plans,
            ),
            StepRun(
                step_index=1,
                state=StepRunState.PLANNED,
                endpoint_plans=(
                    EndpointPlan(
                        broker="fink",
                        origin="lsst",
                        endpoint="sources",
                        candidate_input_from=source_ref,
                    ),
                    EndpointPlan(
                        broker="fink",
                        origin="ztf",
                        endpoint="objects",
                        candidate_input_from=source_ref,
                    ),
                ),
            ),
        ),
    )


@pytest.mark.parametrize(
    ("candidate_ids_by_origin", "expected_downstream", "expected_plan_indexes"),
    [
        (
            {"lsst": ("1701", "1702")},
            [("fink", "lsst", "sources", {"diaObjectId": "1701,1702"})],
            (0,),
        ),
        (
            {"ztf": ("ZTF20abc",)},
            [("fink", "ztf", "objects", {"objectId": "ZTF20abc"})],
            (1,),
        ),
        (
            {"lsst": ("1701",), "ztf": ("ZTF20abc", "ZTF21def")},
            [
                ("fink", "lsst", "sources", {"diaObjectId": "1701"}),
                (
                    "fink",
                    "ztf",
                    "objects",
                    {"objectId": "ZTF20abc,ZTF21def"},
                ),
            ],
            (0, 1),
        ),
        ({}, [], ()),
    ],
)
def test_staged_candidate_routing_is_partitioned_by_plan_origin(
    monkeypatch,
    candidate_ids_by_origin,
    expected_downstream,
    expected_plan_indexes,
):
    _install_origin_routing_normalization(monkeypatch)
    executor = _OriginRoutingExecutor(candidate_ids_by_origin)

    staged = execute_staged_workflow_run(
        _origin_routing_run(), EndpointRegistry(), executor
    )

    assert executor.calls[:2] == [
        (
            "fink",
            "lsst",
            "conesearch",
            {
                "ra": 124.87996115142856,
                "dec": -6.0205001,
                "radius": 300.0,
            },
        ),
        (
            "fink",
            "ztf",
            "conesearch",
            {
                "ra": 124.87996115142856,
                "dec": -6.0205001,
                "radius": 300.0,
            },
        ),
    ]
    assert executor.calls[2:] == expected_downstream
    downstream = staged.run.steps[1]
    assert downstream.state is StepRunState.SUCCEEDED
    assert downstream.execution_plan_indexes == expected_plan_indexes
    assert [call.endpoint_plan.origin for call in staged.bindings[1].bound_calls] == [
        call[1] for call in expected_downstream
    ]


def test_filter_candidate_view_preserves_origin_partition(monkeypatch):
    _install_origin_routing_normalization(monkeypatch)
    executor = _OriginRoutingExecutor(
        {"lsst": ("1701",), "ztf": ("ZTF20abc",)}
    )

    staged = execute_staged_workflow_run(
        _origin_routing_run(through_filter=True), EndpointRegistry(), executor
    )

    assert executor.calls[2:] == [
        ("fink", "lsst", "sources", {"diaObjectId": "1701"}),
        ("fink", "ztf", "objects", {"objectId": "ZTF20abc"}),
    ]
    assert staged.run.steps[1].state is StepRunState.SUCCEEDED
    assert staged.run.steps[1].execution_ids == ()
    assert staged.run.steps[2].execution_plan_indexes == (0, 1)
