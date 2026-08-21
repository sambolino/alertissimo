"""Execution contracts for required versus supplementary physical endpoint plans."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alertissimo.data_layer.execution import EndpointRegistry, ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
)
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.orchestration.binding import bind_workflow_run
from alertissimo.orchestration.ir import (
    ConeSearchStep,
    GetLightcurveStep,
    Source,
    TargetSelector,
    WorkflowIR,
)
from alertissimo.orchestration.normalization import normalize_workflow_execution
from alertissimo.orchestration.pipeline import execute_staged_workflow_run
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import (
    StepRunState,
    WorkflowExecutionError,
    execute_workflow_run,
)


FIXTURE_ROOT = Path(__file__).with_name("fixtures") / "fink" / "lsst"
OBJECT_ID = "170587117485817955"


class FinkLsstExecutor:
    """Return authoritative Fink/LSST fixtures and optionally fail one endpoint."""

    def __init__(self, *, fail_endpoint: str | None = None) -> None:
        self.fail_endpoint = fail_endpoint
        self.calls: list[tuple[str, str, str, dict]] = []
        self.counter = 0

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        assert broker == "fink"
        assert origin == "lsst"
        assert headers is None
        supplied = dict(params or {})
        self.calls.append((broker, origin, endpoint, supplied))
        if endpoint == self.fail_endpoint:
            raise RuntimeError(f"controlled {endpoint} outage")

        fixture = {
            "conesearch": "conesearch.json",
            "sources": "sources.json",
            "fp": "fp.json",
        }[endpoint]
        self.counter += 1
        return ExecutionResult(
            payload=json.loads((FIXTURE_ROOT / fixture).read_text(encoding="utf-8")),
            execution_provenance=InternalExecutionProvenance(
                internal_execution_id=InternalExecutionId(
                    f"execution:supplementary-test:{self.counter}"
                ),
                broker=broker,
                origin=origin,
                endpoint=endpoint,
                params=supplied,
                status="success",
                transport="fixture",
            ),
        )


def _targetless_workflow() -> WorkflowIR:
    return WorkflowIR(
        steps=[
            ConeSearchStep(
                semantic_type="summary",
                ra=62.45763,
                dec=-48.48149,
                radius=5.0,
                sources=[Source(broker="fink", origin="lsst")],
            ),
            GetLightcurveStep(
                sources=[Source(broker="fink", origin="lsst")]
            ),
        ]
    )


def test_staged_lightcurve_survives_failed_forced_photometry_supplement():
    graph = build_capability_graph()
    run = plan_workflow(_targetless_workflow(), graph)
    lightcurve = run.steps[1]

    assert [plan.endpoint for plan in lightcurve.endpoint_plans] == ["sources", "fp"]
    assert [plan.required for plan in lightcurve.endpoint_plans] == [True, False]

    executor = FinkLsstExecutor(fail_endpoint="fp")
    staged = execute_staged_workflow_run(run, EndpointRegistry(), executor)

    completed = staged.run.steps[1]
    assert completed.state is StepRunState.SUCCEEDED
    assert completed.error is None
    assert completed.execution_plan_indexes == (0,)
    assert len(completed.execution_ids) == 1
    assert len(completed.warnings) == 1
    assert "fink/lsst/fp" in completed.warnings[0]
    assert "controlled fp outage" in completed.warnings[0]

    assert [
        execution.execution_provenance.endpoint
        for execution in staged.execution.steps[1].executions
    ] == ["sources"]
    assert len(staged.normalized.steps[1].executions) == 1
    assert staged.normalized.steps[1].executions[0].execution_id == completed.execution_ids[0]

    assert [endpoint for _, _, endpoint, _ in executor.calls] == [
        "conesearch",
        "sources",
        "fp",
    ]


def test_required_primary_lightcurve_failure_remains_fail_fast():
    graph = build_capability_graph()
    workflow = WorkflowIR(
        steps=[
            GetLightcurveStep(
                target=TargetSelector(ids=[OBJECT_ID], kind="object"),
                sources=[Source(broker="fink", origin="lsst")],
            )
        ]
    )
    run = plan_workflow(workflow, graph)
    bindings = bind_workflow_run(run, EndpointRegistry())
    executor = FinkLsstExecutor(fail_endpoint="sources")

    with pytest.raises(WorkflowExecutionError) as caught:
        execute_workflow_run(run, bindings, executor)

    failed = caught.value.workflow_run.steps[0]
    assert failed.state is StepRunState.FAILED
    assert failed.execution_ids == ()
    assert failed.execution_plan_indexes == ()
    assert failed.warnings == ()
    assert "controlled sources outage" in (failed.error or "")
    assert [endpoint for _, _, endpoint, _ in executor.calls] == ["sources"]


def test_static_lightcurve_normalizes_primary_when_supplement_fails():
    graph = build_capability_graph()
    workflow = WorkflowIR(
        steps=[
            GetLightcurveStep(
                target=TargetSelector(ids=[OBJECT_ID], kind="object"),
                sources=[Source(broker="fink", origin="lsst")],
            )
        ]
    )
    run = plan_workflow(workflow, graph)
    bindings = bind_workflow_run(run, EndpointRegistry())
    executor = FinkLsstExecutor(fail_endpoint="fp")

    executed = execute_workflow_run(run, bindings, executor)
    normalized = normalize_workflow_execution(executed)

    step = executed.run.steps[0]
    assert step.state is StepRunState.SUCCEEDED
    assert step.execution_plan_indexes == (0,)
    assert len(step.warnings) == 1
    assert [
        execution.execution_provenance.endpoint
        for execution in executed.steps[0].executions
    ] == ["sources"]
    assert len(normalized.steps[0].executions) == 1
