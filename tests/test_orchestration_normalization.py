"""Offline tests for the orchestration-to-Portfolio semantic bridge."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
)
from alertissimo.orchestration.ir import LookupStep, WorkflowIR
from alertissimo.orchestration.normalization import (
    WorkflowNormalizationAlignmentError,
    normalize_execution,
    normalize_step_execution,
    normalize_workflow_execution,
)
from alertissimo.orchestration.runtime import (
    EndpointPlan,
    StepExecutionResult,
    StepRun,
    StepRunState,
    WorkflowExecutionResult,
    WorkflowRun,
)


FIXTURES = Path(__file__).parent / "fixtures"


def _execution(
    broker: str, origin: str, endpoint: str, fixture: Path, execution_id: str
) -> ExecutionResult:
    return ExecutionResult(
        payload=json.loads(fixture.read_text(encoding="utf-8")),
        execution_provenance=InternalExecutionProvenance(
            internal_execution_id=InternalExecutionId(execution_id),
            broker=broker,
            origin=origin,
            endpoint=endpoint,
        ),
    )


def _alerce(execution_id: str = "execution:alerce") -> ExecutionResult:
    return _execution(
        "alerce",
        "ztf",
        "query_object",
        FIXTURES / "alerce" / "ztf" / "query_object.json",
        execution_id,
    )


def _lasair(execution_id: str = "execution:lasair") -> ExecutionResult:
    return _execution(
        "lasair",
        "ztf",
        "object",
        FIXTURES / "lasair" / "ztf" / "object.json",
        execution_id,
    )


def _workflow_result(
    executions_by_step: tuple[tuple[ExecutionResult, ...], ...],
) -> WorkflowExecutionResult:
    workflow = WorkflowIR(
        steps=tuple(
            LookupStep(id=f"target-{index}")
            for index in range(len(executions_by_step))
        )
    )
    run = WorkflowRun(
        workflow=workflow,
        steps=tuple(
            StepRun(
                step_index=index,
                state=StepRunState.SUCCEEDED,
                endpoint_plans=tuple(
                    EndpointPlan(
                        broker=execution.execution_provenance.broker,
                        origin=execution.execution_provenance.origin,
                        endpoint=execution.execution_provenance.endpoint,
                    )
                    for execution in executions
                ),
                execution_ids=tuple(
                    execution.internal_execution_id.value for execution in executions
                ),
            )
            for index, executions in enumerate(executions_by_step)
        ),
    )
    return WorkflowExecutionResult(
        run=run,
        steps=tuple(
            StepExecutionResult(step_index=index, executions=executions)
            for index, executions in enumerate(executions_by_step)
        ),
    )


@pytest.mark.parametrize(
    ("execution", "expected_family"),
    [
        (_alerce(), "summary@ztf:alerce"),
        (_lasair(), "summary@ztf:lasair"),
    ],
)
def test_real_execution_normalizes_with_provenance_and_record_sources(
    execution, expected_family
):
    portfolio = normalize_execution(execution)

    assert expected_family in {record.semantic_type for record in portfolio.records}
    assert portfolio.executions == (execution.execution_provenance,)
    assert portfolio.records
    assert all(
        record.internal_source is not None
        and record.internal_source.internal_execution_id
        == execution.internal_execution_id
        for record in portfolio.records
    )


def test_two_provider_executions_in_one_step_remain_independent_and_ordered():
    result = normalize_workflow_execution(_workflow_result(((_alerce(), _lasair()),)))

    assert len(result.steps) == 1
    outputs = result.steps[0].portfolios
    assert [output.execution_id for output in outputs] == [
        "execution:alerce",
        "execution:lasair",
    ]
    assert outputs[0].portfolio is not outputs[1].portfolio
    assert (
        outputs[0].portfolio.internal_portfolio_id
        != outputs[1].portfolio.internal_portfolio_id
    )


def test_repeated_step_occurrences_stay_distinct():
    result = normalize_workflow_execution(
        _workflow_result(
            ((_lasair("execution:first"),), (_lasair("execution:second"),))
        )
    )

    assert [step.step_index for step in result.steps] == [0, 1]
    assert [step.portfolios[0].execution_id for step in result.steps] == [
        "execution:first",
        "execution:second",
    ]


def test_execution_id_misalignment_is_rejected_before_normalization(monkeypatch):
    execution_result = _workflow_result(((_alerce(),),))
    bad_step = execution_result.run.steps[0].model_copy(
        update={"execution_ids": ("execution:wrong",)}
    )
    bad_run = execution_result.run.model_copy(update={"steps": (bad_step,)})
    inconsistent = WorkflowExecutionResult(run=bad_run, steps=execution_result.steps)
    called = False

    def unexpected_normalization(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("normalization started before alignment validation")

    monkeypatch.setattr(
        "alertissimo.orchestration.normalization.normalize.normalize_execution",
        unexpected_normalization,
    )

    with pytest.raises(
        WorkflowNormalizationAlignmentError, match="execution IDs do not align"
    ):
        normalize_workflow_execution(inconsistent)
    assert called is False


def test_endpoint_plan_count_mismatch_is_rejected_before_normalization(monkeypatch):
    execution_result = _workflow_result(((_alerce(),),))
    bad_step = execution_result.run.steps[0].model_copy(
        update={"endpoint_plans": ()}
    )
    bad_run = execution_result.run.model_copy(update={"steps": (bad_step,)})
    inconsistent = WorkflowExecutionResult(run=bad_run, steps=execution_result.steps)
    called = False

    def unexpected_normalization(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        "alertissimo.orchestration.normalization.normalize.normalize_execution",
        unexpected_normalization,
    )

    with pytest.raises(
        WorkflowNormalizationAlignmentError, match="endpoint plan count"
    ):
        normalize_workflow_execution(inconsistent)
    assert called is False


@pytest.mark.parametrize("field", ["broker", "origin", "endpoint"])
def test_endpoint_identity_mismatch_is_rejected_before_normalization(
    monkeypatch, field
):
    execution_result = _workflow_result(((_alerce(),),))
    step = execution_result.run.steps[0]
    bad_plan = step.endpoint_plans[0].model_copy(update={field: f"wrong-{field}"})
    bad_step = step.model_copy(update={"endpoint_plans": (bad_plan,)})
    bad_run = execution_result.run.model_copy(update={"steps": (bad_step,)})
    inconsistent = WorkflowExecutionResult(run=bad_run, steps=execution_result.steps)
    called = False

    def unexpected_normalization(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        "alertissimo.orchestration.normalization.normalize.normalize_execution",
        unexpected_normalization,
    )

    with pytest.raises(
        WorkflowNormalizationAlignmentError,
        match=(
            r"step_index 0 execution position 0 endpoint identity does not align: "
            r"planned broker=.*origin=.*endpoint=.*actual broker=.*origin=.*endpoint="
        ),
    ):
        normalize_workflow_execution(inconsistent)
    assert called is False


def test_standalone_step_normalization_supports_completed_failure_path_output():
    result = normalize_step_execution(
        StepExecutionResult(step_index=4, executions=(_alerce(),))
    )

    assert result.step_index == 4
    assert result.portfolios[0].execution_id == "execution:alerce"
