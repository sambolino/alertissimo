"""Offline tests for the orchestration-to-Portfolio semantic bridge."""

from __future__ import annotations

from alertissimo.orchestration.ir import TargetSelector

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
            LookupStep(
                target=TargetSelector(ids=[f"target-{index}"], kind="object")
            )
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
    (portfolio,) = normalize_execution(execution)

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
    outputs = result.steps[0].executions
    assert [output.execution_id for output in outputs] == [
        "execution:alerce",
        "execution:lasair",
    ]
    assert outputs[0].portfolios[0] is not outputs[1].portfolios[0]
    assert (
        outputs[0].portfolios[0].internal_portfolio_id
        != outputs[1].portfolios[0].internal_portfolio_id
    )


def test_repeated_step_occurrences_stay_distinct():
    result = normalize_workflow_execution(
        _workflow_result(
            ((_lasair("execution:first"),), (_lasair("execution:second"),))
        )
    )

    assert [step.step_index for step in result.steps] == [0, 1]
    assert [step.executions[0].execution_id for step in result.steps] == [
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
    assert result.executions[0].execution_id == "execution:alerce"


@pytest.mark.parametrize(("endpoint", "filename", "expected"), (("anomaly", "anomaly.json", 10), ("statistics", "statistics_day.json", 0)))
def test_fink_execution_wrapper_retains_multi_or_zero_portfolios(endpoint, filename, expected):
    execution = _execution(
        "fink", "ztf", endpoint,
        FIXTURES / "fink" / "ztf" / filename,
        f"execution:fink:{endpoint}",
    )
    result = normalize_step_execution(StepExecutionResult(step_index=0, executions=(execution,)))
    assert len(result.executions) == 1
    assert result.executions[0].execution_id == f"execution:fink:{endpoint}"
    assert len(result.executions[0].portfolios) == expected


def test_one_multi_id_execution_normalizes_to_two_object_portfolios():
    """Combine untouched rows from two authoritative objects endpoint captures."""
    from alertissimo.data_layer.execution import EndpointRegistry
    from alertissimo.orchestration.binding import bind_workflow_run
    from alertissimo.orchestration.ir import GetLightcurveStep, Source
    from alertissimo.orchestration.planner import plan_workflow
    from alertissimo.orchestration.runtime import execute_workflow_run
    from alertissimo.data_layer.runtime.capability_graph import build_capability_graph

    first_rows = json.loads(
        (FIXTURES / "fink" / "ztf" / "objects_withupperlim.json").read_text(encoding="utf-8")
    )
    second_rows = json.loads(
        (FIXTURES / "ui" / "sources" / "fink_pair" / "ztf_objects.json").read_text(encoding="utf-8")
    )
    combined_rows = first_rows + second_rows
    expected_ids = ("ZTF21abfmbix", "ZTF18acurdih")
    assert {row["i:objectId"] for row in first_rows} == {expected_ids[0]}
    assert {row["i:objectId"] for row in second_rows} == {expected_ids[1]}
    assert len(first_rows) > 1  # repeated rows must stay grouped below

    class FrozenObjectsExecutor:
        def __init__(self):
            self.calls = []

        def execute(self, *, broker, origin, endpoint, params):
            self.calls.append((broker, origin, endpoint, dict(params)))
            return ExecutionResult(
                payload=combined_rows,
                execution_provenance=InternalExecutionProvenance(
                    internal_execution_id=InternalExecutionId("execution:fink:objects:multi"),
                    broker=broker,
                    origin=origin,
                    endpoint=endpoint,
                    params=params,
                ),
            )

    workflow = WorkflowIR(steps=[GetLightcurveStep(
        target=TargetSelector(ids=list(expected_ids), kind="object"),
        sources=[Source(broker="fink", origin="ztf")],
    )])
    assert len(workflow.steps) == 1 and workflow.steps[0].target.ids == list(expected_ids)
    run = plan_workflow(workflow, build_capability_graph())
    assert [(plan.broker, plan.origin, plan.endpoint) for plan in run.steps[0].endpoint_plans] == [
        ("fink", "ztf", "objects")
    ]
    bindings = bind_workflow_run(run, EndpointRegistry())
    assert len(bindings) == len(bindings[0].bound_calls) == 1
    assert bindings[0].bound_calls[0].params == {"objectId": ",".join(expected_ids)}

    executor = FrozenObjectsExecutor()
    execution = execute_workflow_run(run, bindings, executor)
    assert len(executor.calls) == 1
    assert len(execution.steps[0].executions) == 1
    normalized = normalize_workflow_execution(execution)
    assert len(normalized.steps[0].executions) == 1
    wrapper = normalized.steps[0].executions[0]
    assert len(wrapper.portfolios) == 2
    assert len({p.internal_portfolio_id for p in wrapper.portfolios}) == 2

    portfolio_ids = []
    for portfolio in wrapper.portfolios:
        raw_object_ids = {
            combined_rows[record.internal_source.payload_index]["i:objectId"]
            for record in portfolio.records
            if record.internal_source is not None
            and record.internal_source.payload_index is not None
        }
        assert len(raw_object_ids) == 1
        portfolio_ids.extend(raw_object_ids)
        primary_identity_ids = {
            record.fields["identity.object_id"]
            for record in portfolio.records
            if record.semantic_type == "summary@ztf:fink"
            and "identity.object_id" in record.fields
        }
        assert primary_identity_ids == raw_object_ids
        assert portfolio.executions == (
            execution.steps[0].executions[0].execution_provenance,
        )
        assert all(
            record.internal_source is None
            or record.internal_source.internal_execution_id.value
            == "execution:fink:objects:multi"
            for record in portfolio.records
        )
    assert set(portfolio_ids) == set(expected_ids)
    assert sum(
        record.internal_source is not None
        and record.internal_source.payload_index is not None
        and combined_rows[record.internal_source.payload_index]["i:objectId"] == expected_ids[0]
        for portfolio in wrapper.portfolios
        for record in portfolio.records
    ) > 1


@pytest.mark.parametrize(
    ("origin", "endpoint", "physical_name"),
    [("ztf", "sherlock_objects", "objectIds"),
     ("lsst", "sherlock_object", "objectId")],
)
def test_synthetic_lasair_sherlock_aggregate_keeps_two_objects_separate(
    origin, endpoint, physical_name
):
    """Synthetic contract: no provider capture or entity resolution is involved."""
    from alertissimo.data_layer.execution import EndpointRegistry
    from alertissimo.orchestration.binding import bind_endpoint
    from alertissimo.orchestration.ir import GetCrossmatchStep

    payload = {
        "classifications": {
            "A": ["SN", "description A"],
            "B": ["AGN", "description B"],
        },
        "crossmatches": [
            {"transient_object_id": "A", "catalogue_table_name": "Gaia DR3",
             "catalogue_object_id": "catalogue-A"},
            {"transient_object_id": "B", "catalogue_table_name": "Gaia DR3",
             "catalogue_object_id": "catalogue-B"},
        ],
    }
    plan = EndpointPlan(broker="lasair", origin=origin, endpoint=endpoint)
    call = bind_endpoint(
        GetCrossmatchStep(target=TargetSelector(ids=["A", "B"], kind="object")), plan, EndpointRegistry()
    )
    assert call.params == {physical_name: "A,B"}  # one bound physical call

    provenance = InternalExecutionProvenance(
        InternalExecutionId(f"execution:lasair:{origin}:sherlock:synthetic"),
        "lasair", origin, endpoint, params=call.params,
    )
    execution = ExecutionResult(payload=payload, execution_provenance=provenance)
    executions = (execution,)
    assert len(executions) == 1
    normalized = normalize_step_execution(
        StepExecutionResult(step_index=0, executions=executions)
    )
    assert len(normalized.executions) == 1  # one ExecutionPortfolioResult
    wrapper = normalized.executions[0]
    assert len(wrapper.portfolios) == 2
    assert len({p.internal_portfolio_id for p in wrapper.portfolios}) == 2

    raw_ids_by_index = {
        "sherlock_object_classifications": ("A", "B"),
        "sherlock_objects_classifications": ("A", "B"),
        "sherlock_object_crossmatches": ("A", "B"),
        "sherlock_objects_crossmatches": ("A", "B"),
    }
    seen = set()
    for portfolio in wrapper.portfolios:
        raw_ids = {
            raw_ids_by_index[record.internal_source.payload_key][
                record.internal_source.payload_index
            ]
            for record in portfolio.records
            if record.internal_source is not None
            and record.internal_source.payload_key in raw_ids_by_index
        }
        assert len(raw_ids) == 1
        (transient_id,) = tuple(raw_ids)
        seen.add(transient_id)
        assert {r.internal_source.payload_key.split("_")[-1]
                for r in portfolio.records if r.internal_source is not None} >= {
                    "classifications", "crossmatches"
                }
        assert portfolio.executions == (provenance,)
        assert portfolio.edges == ()  # no composition/entity-resolution stage
        catalogue_ids = {
            r.fields.get("identity.object_id") for r in portfolio.records
            if r.semantic_type == "crossmatch@gaia:lasair"
        }
        assert catalogue_ids == {f"catalogue-{transient_id}"}
        assert transient_id not in catalogue_ids
    assert seen == {"A", "B"}
