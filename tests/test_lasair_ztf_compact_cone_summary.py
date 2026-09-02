"""Lasair/ZTF cone discovery gains compact summaries without changing IR."""

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
from alertissimo.dsl import compile_surface, parse_surface_script
from alertissimo.orchestration.binding import bind_endpoint_calls
from alertissimo.orchestration.pipeline import execute_staged_workflow_run
from alertissimo.orchestration.planner import plan_workflow


CAPTURE = (
    Path(__file__).with_name("fixtures")
    / "lasair"
    / "ztf"
    / "capture_20260813T110413Z"
)
DSL = """objects from ztf via lasair
inside (124.87996115142856, -6.0205001, 5arcsec)
"""


def _planned():
    graph = build_capability_graph()
    workflow = compile_surface(parse_surface_script(DSL), graph=graph).workflow
    return workflow, plan_workflow(workflow, graph)


def _ztf_id(index: int) -> str:
    letters = []
    value = index
    for _ in range(7):
        letters.append(chr(ord("a") + value % 26))
        value //= 26
    return "ZTF20" + "".join(reversed(letters))


class FixtureExecutor:
    def __init__(self, *, query_error: Exception | None = None, empty=False):
        self.query_error = query_error
        self.empty = empty
        self.calls: list[tuple[str, str, str, dict]] = []
        self.counter = 0

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        assert headers is None
        supplied = dict(params or {})
        self.calls.append((broker, origin, endpoint, supplied))
        if endpoint == "cone":
            payload = [] if self.empty else json.loads(
                (CAPTURE / "cone_all.json").read_text(encoding="utf-8")
            )
        elif endpoint == "query":
            if self.query_error is not None:
                raise self.query_error
            payload = json.loads(
                (CAPTURE / "query_core.json").read_text(encoding="utf-8")
            )
        else:  # pragma: no cover - changed planning is the regression.
            raise AssertionError(f"unexpected endpoint {endpoint!r}")

        self.counter += 1
        return ExecutionResult(
            payload=payload,
            execution_provenance=InternalExecutionProvenance(
                internal_execution_id=InternalExecutionId(
                    f"execution:lasair-summary:{self.counter}"
                ),
                broker=broker,
                origin=origin,
                endpoint=endpoint,
                params=supplied,
                status="success",
                transport="fixture",
            ),
        )


def test_planner_keeps_one_ir_step_with_two_physical_plans():
    workflow, run = _planned()

    assert len(workflow.steps) == 1
    assert workflow.steps[0].op == "cone_search"
    plans = run.steps[0].endpoint_plans
    assert [plan.endpoint for plan in plans] == ["cone", "query"]
    assert [plan.required for plan in plans] == [True, False]
    assert plans[1].candidate_input_from_plan.plan_index == 0
    assert plans[1].request_params == {
        "selected": (
            "objects.objectId,objects.ramean,objects.decmean,objects.ncand,"
            "objects.jdmin,objects.jdmax"
        ),
        "tables": "objects",
        "limit": 100,
        "offset": 0,
    }


def test_query_binding_validates_and_batches_normalized_ids():
    workflow, run = _planned()
    query_plan = run.steps[0].endpoint_plans[1]
    object_ids = tuple(_ztf_id(index) for index in range(201))

    calls = bind_endpoint_calls(
        workflow.steps[0],
        query_plan,
        EndpointRegistry(),
        runtime_values={"target_id": object_ids},
    )

    assert len(calls) == 3
    assert [call.params["limit"] for call in calls] == [100, 100, 100]
    assert all(len(call.params["conditions"]) < 4096 for call in calls)
    assert calls[0].params["conditions"].startswith(
        'objects.objectId IN ("ZTF20'
    )
    assert calls[-1].params["conditions"] == (
        f'objects.objectId IN ("{object_ids[-1]}")'
    )


def test_staged_cone_query_consolidates_rich_summary_fields():
    _workflow, run = _planned()
    executor = FixtureExecutor()

    staged = execute_staged_workflow_run(run, EndpointRegistry(), executor)

    assert [endpoint for _, _, endpoint, _ in executor.calls] == ["cone", "query"]
    assert executor.calls[1][3]["conditions"] == (
        'objects.objectId IN ("ZTF20acpwljl")'
    )
    step_run = staged.run.steps[0]
    assert step_run.execution_plan_indexes == (0, 1)
    assert step_run.warnings == ()
    assert len(staged.normalized.steps[0].portfolios) == 1
    summary_fields = [
        record.fields
        for record in staged.normalized.steps[0].portfolios[0].records
        if record.semantic_type == "summary@ztf:lasair"
    ]
    assert any(fields.get("detection_count") == 35 for fields in summary_fields)
    assert any(fields.get("position.ra") == 124.87996115142856 for fields in summary_fields)
    assert any("time.first_mjd" in fields for fields in summary_fields)
    assert any("time.last_mjd" in fields for fields in summary_fields)


def test_failed_summary_query_preserves_thin_cone_results_with_warning():
    _workflow, run = _planned()
    executor = FixtureExecutor(query_error=RuntimeError("controlled query outage"))

    staged = execute_staged_workflow_run(run, EndpointRegistry(), executor)

    step_run = staged.run.steps[0]
    assert step_run.state.value == "succeeded"
    assert step_run.execution_plan_indexes == (0,)
    assert len(step_run.warnings) == 1
    assert "controlled query outage" in step_run.warnings[0]
    assert len(staged.normalized.steps[0].portfolios) == 1


def test_empty_cone_makes_summary_query_vacuous():
    _workflow, run = _planned()
    executor = FixtureExecutor(empty=True)

    staged = execute_staged_workflow_run(run, EndpointRegistry(), executor)

    assert [endpoint for _, _, endpoint, _ in executor.calls] == ["cone"]
    assert staged.run.steps[0].vacuous_plan_indexes == (1,)
    assert staged.run.steps[0].warnings == ()
    assert staged.normalized.steps[0].portfolios == ()


@pytest.mark.parametrize(
    "object_id",
    ["ZTF20acpwljl\" OR 1=1", "not-a-ztf-id"],
)
def test_invalid_provider_identity_cannot_become_sql(object_id):
    workflow, run = _planned()
    query_plan = run.steps[0].endpoint_plans[1]

    with pytest.raises(ValueError, match="invalid SQL membership values"):
        bind_endpoint_calls(
            workflow.steps[0],
            query_plan,
            EndpointRegistry(),
            runtime_values={"target_id": (object_id,)},
        )
