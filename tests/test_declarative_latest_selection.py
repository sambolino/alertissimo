"""Generic ``latest N`` planning and pre-downstream semantic selection."""

from __future__ import annotations

from itertools import count
from pathlib import Path

from alertissimo.data_layer.execution import EndpointRegistry, ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
)
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import compile_surface_to_ir, parse_surface_script
from alertissimo.orchestration.binding import bind_endpoint_calls
from alertissimo.orchestration.local_semantics import finalize_local_semantics
from alertissimo.orchestration.normalization import summary_object_identity
from alertissimo.orchestration.pipeline import execute_staged_workflow_run
from alertissimo.orchestration.planner import plan_step, plan_workflow


OLD = "ZTF20aaaaaaa"
MIDDLE = "ZTF20bbbbbbb"
LATEST = "ZTF20ccccccc"
DSL = """objects from ztf via alerce
inside (124.879961, -6.020500, 300arcsec)
latest 1
where exists classification.best.class
confirm by 2 via fink, lasair
with lightcurve via alerce
"""


def _compile_and_plan(source: str = DSL):
    graph = build_capability_graph()
    workflow = compile_surface_to_ir(parse_surface_script(source), graph=graph)
    return workflow, plan_workflow(workflow, graph)


def _alerce_row(object_id: str, last_mjd: float) -> dict:
    return {
        "oid": object_id,
        "meanra": 124.879961,
        "meandec": -6.020500,
        "firstmjd": last_mjd - 10,
        "lastmjd": last_mjd,
        "ndet": 2,
        "class": "SN",
        "classifier": "fixture",
        "probability": 0.9,
    }


class _Executor:
    def __init__(self):
        self.calls: list[tuple[str, str, str, dict]] = []
        self._ids = count(1)

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        del headers
        supplied = dict(params or {})
        self.calls.append((broker, origin, endpoint, supplied))
        if (broker, origin, endpoint) == ("alerce", "ztf", "query_objects"):
            # Deliberately violate the provider-side page_size optimization. The
            # normalized residual must still choose the globally latest candidate.
            payload = {
                "items": [
                    _alerce_row(OLD, 60000.0),
                    _alerce_row(LATEST, 62000.0),
                    _alerce_row(MIDDLE, 61000.0),
                ]
            }
        elif (broker, origin, endpoint) == ("fink", "ztf", "objects"):
            assert supplied["objectId"] == LATEST
            payload = [
                {
                    "i:objectId": LATEST,
                    "i:candid": 1642249732315015013,
                    "v:classification": "SN",
                }
            ]
        elif (broker, origin, endpoint) == ("lasair", "ztf", "objects"):
            assert supplied["objectIds"] == LATEST
            payload = [
                {
                    "objectId": LATEST,
                    "objectData": {
                        "ncand": 2,
                        "jdmin": 2460000.5,
                        "jdmax": 2460001.5,
                        "ramean": 124.879961,
                        "decmean": -6.020500,
                    },
                    "sherlock": {"classification": "SN"},
                }
            ]
        elif (broker, origin, endpoint) == ("alerce", "ztf", "query_lightcurve"):
            assert supplied["oid"] == LATEST
            payload = {"detections": [], "non_detections": []}
        else:  # pragma: no cover - changed endpoint planning is the regression.
            raise AssertionError(f"unexpected endpoint {(broker, origin, endpoint)!r}")

        return ExecutionResult(
            payload=payload,
            execution_provenance=InternalExecutionProvenance(
                internal_execution_id=InternalExecutionId(
                    f"execution:latest:{next(self._ids)}"
                ),
                broker=broker,
                origin=origin,
                endpoint=endpoint,
                params=supplied,
            ),
        )


def test_single_source_latest_pushdown_is_declared_and_bound_generically():
    workflow, run = _compile_and_plan(
        "objects from ztf via alerce\n"
        "inside (124.879961, -6.020500, 300arcsec)\n"
        "latest 1\n"
    )
    search = workflow.steps[0]
    plan = run.steps[0].endpoint_plans[0]

    assert plan.selection_realization.pushdown == search.selection
    assert plan.selection_realization.residual == search.selection
    assert plan.selection_realization.params == {
        "page": 1,
        "page_size": 1,
        "order_by": "lastmjd",
        "order_mode": "DESC",
    }
    calls = bind_endpoint_calls(search, plan, EndpointRegistry())
    assert calls[0].params == {
        "ra": 124.879961,
        "dec": -6.0205,
        "radius": 300.0,
        "page": 1,
        "page_size": 1,
        "order_by": "lastmjd",
        "order_mode": "DESC",
    }


def test_latest_is_not_pushed_ahead_of_a_residual_search_predicate():
    workflow, run = _compile_and_plan()
    search = workflow.steps[0]
    plan = run.steps[0].endpoint_plans[0]

    assert search.predicate is not None
    assert plan.predicate_realization.residual is not None
    assert plan.selection_realization.pushdown is None
    assert plan.selection_realization.params == {}


def test_multi_source_latest_keeps_global_residual_without_per_source_limit():
    graph = build_capability_graph()
    workflow = compile_surface_to_ir(
        parse_surface_script("objects from lsst, ztf via alerce\nlatest 2\n"),
        graph=graph,
    )
    plans = plan_step(workflow.steps[0], graph)

    assert len(plans) == 2
    assert all(plan.selection_realization.pushdown is None for plan in plans)
    assert all(plan.selection_realization.params == {} for plan in plans)
    assert all(
        plan.selection_realization.residual == workflow.steps[0].selection
        for plan in plans
    )


def test_latest_is_enforced_before_confirm_and_downstream_binding():
    _workflow, run = _compile_and_plan()
    executor = _Executor()

    staged = execute_staged_workflow_run(run, EndpointRegistry(), executor)
    finalized = finalize_local_semantics(staged.normalized)

    assert [endpoint for _, _, endpoint, _ in executor.calls] == [
        "query_objects",
        "objects",
        "objects",
        "query_lightcurve",
    ]
    assert len(finalized.steps[0].portfolios) == 1
    assert summary_object_identity(finalized.steps[0].portfolios[0]) == (
        "ztf",
        LATEST,
    )
    assert {
        call.params.get("objectId") or call.params.get("objectIds") or call.params.get("oid")
        for binding in staged.bindings[1:]
        for call in binding.bound_calls
    } == {LATEST}


def test_planner_source_contains_no_provider_specific_realization_literals():
    source = (
        Path(__file__).parents[1]
        / "alertissimo"
        / "orchestration"
        / "planner"
        / "planner.py"
    ).read_text(encoding="utf-8")

    for literal in ("lasair", "alerce", "lastmjd", "objects.objectid"):
        assert literal not in source.lower()
