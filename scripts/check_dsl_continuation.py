#!/usr/bin/env python3
"""Offline acceptance for the two-call UI DSL workflow contract."""

from __future__ import annotations

import json

import alertissimo.api as api
from alertissimo.dsl import SurfaceFragment, SurfaceScript
from alertissimo.orchestration.pipeline import StagedWorkflowResult
from scripts.smoke.executors import FixtureEndpointExecutor, fixture_key


CANDIDATE_ID = "ZTF20acpwljl"
RA = 124.87996115142856
DEC = -6.0205001
RADIUS_ARCSEC = 5.0

FIRST_PASS = f"""objects from ztf via lasair
inside ({RA}, {DEC}, {RADIUS_ARCSEC}arcsec)
with lightcurve via fink
"""

SECOND_PASS = """filter detection@ztf:fink.quality.real_bogus >= 0.8
with lightcurve via lasair
"""


def _executor() -> FixtureEndpointExecutor:
    return FixtureEndpointExecutor(
        {
            fixture_key(
                "lasair",
                "ztf",
                "cone",
                ra=RA,
                dec=DEC,
                radius=RADIUS_ARCSEC,
            ): "../../../tests/fixtures/lasair/ztf/capture_20260813T110413Z/cone_all.json",
            fixture_key(
                "fink",
                "ztf",
                "objects",
                objectId=CANDIDATE_ID,
            ): "fink_objects_ztf20acpwljl_quality.json",
            fixture_key(
                "lasair",
                "ztf",
                "lightcurves",
                objectIds=CANDIDATE_ID,
            ): "lasair_lightcurves_ztf20acpwljl.json",
        }
    )


def main() -> int:
    executor = _executor()

    print("=== ALERTISSIMO UI DSL TWO-CALL ACCEPTANCE ===")

    initial_fragment = api.validate_dsl(SECOND_PASS)
    if initial_fragment.is_valid or initial_fragment.parse_error is None:
        raise RuntimeError("a fragment was accepted before any workflow existed")
    print("PASS: fragment-first request rejected without provider calls")

    print("--- first pass ---")
    print(FIRST_PASS.rstrip())
    first_validation = api.validate_dsl(FIRST_PASS)
    if not first_validation.is_valid or not first_validation.is_runnable:
        raise RuntimeError(f"first-pass validation failed: {first_validation!r}")
    if executor.calls:
        raise RuntimeError("first-pass validation contacted a provider")

    first = api.execute_dsl(FIRST_PASS, executor=executor)
    first_payload = json.loads(first.to_json())
    if not isinstance(first.surface, SurfaceScript):
        raise RuntimeError("first pass did not parse as a complete DSL script")
    if first_payload["source"] != FIRST_PASS:
        raise RuntimeError("first JSON payload did not preserve submitted DSL text")
    if [step["op"] for step in first_payload["workflow"]["steps"]] != [
        "cone_search",
        "get_lightcurve",
    ]:
        raise RuntimeError("first JSON payload does not expose the canonical WorkflowIR")
    if api._active_workflow is not first.staged:
        raise RuntimeError("execute_dsl did not retain its generic staged state")
    if not isinstance(api._active_workflow, StagedWorkflowResult):
        raise RuntimeError("active state is not a StagedWorkflowResult")
    if hasattr(api._active_workflow, "source") or hasattr(api._active_workflow, "surface"):
        raise RuntimeError("active middle-layer state leaked DSL artifacts")
    if len(executor.calls) != 2:
        raise RuntimeError(
            f"first pass expected 2 physical calls, observed {len(executor.calls)}"
        )
    if len(first.portfolios) != 1:
        raise RuntimeError(
            f"first pass expected one Portfolio, observed {len(first.portfolios)}"
        )
    first_calls = tuple(executor.calls)

    print("--- second pass fragment ---")
    print(SECOND_PASS.rstrip())
    validation = api.validate_dsl(SECOND_PASS)
    if not validation.is_valid or not validation.is_runnable:
        raise RuntimeError(f"continuation validation failed: {validation!r}")
    if not isinstance(validation.surface, SurfaceFragment):
        raise RuntimeError("second pass did not parse as a DSL fragment")
    if tuple(validation.compilation.workflow.steps[: len(first.workflow.steps)]) != tuple(
        first.workflow.steps
    ):
        raise RuntimeError("fragment validation changed the canonical prior IR prefix")
    if tuple(executor.calls) != first_calls:
        raise RuntimeError("fragment validation contacted a provider")

    calls_before = first_calls
    second = api.execute_dsl(
        SECOND_PASS,
        executor=executor,
    )
    second_payload = json.loads(second.to_json())
    if second_payload["source"] != SECOND_PASS:
        raise RuntimeError("second JSON payload should contain only the submitted fragment")
    if [step["op"] for step in second_payload["workflow"]["steps"]] != [
        "cone_search",
        "get_lightcurve",
        "filter",
        "get_lightcurve",
    ]:
        raise RuntimeError("second JSON payload does not expose the extended WorkflowIR")
    if api._active_workflow is not second.staged:
        raise RuntimeError("second execute_dsl call did not replace active staged state")

    new_calls = tuple(executor.calls[len(calls_before) :])
    if len(new_calls) != 1:
        raise RuntimeError(
            "continuation must make exactly one new provider call; "
            f"observed {len(new_calls)}: {new_calls!r}"
        )
    broker, origin, endpoint, params = new_calls[0]
    if (broker, origin, endpoint) != ("lasair", "ztf", "lightcurves"):
        raise RuntimeError(
            "continuation repeated old provider work instead of only adding the "
            f"Lasair enrichment: {new_calls[0]!r}"
        )
    if params != {"objectIds": CANDIDATE_ID}:
        raise RuntimeError(f"unexpected continuation target binding: {params!r}")

    if len(second.portfolios) != 1:
        raise RuntimeError(
            f"second pass expected one surviving Portfolio, observed {len(second.portfolios)}"
        )
    semantic_types = {
        record.semantic_type
        for portfolio in second.portfolios
        for record in portfolio.records
    }
    if not any(value.startswith("detection@ztf:fink") for value in semantic_types):
        raise RuntimeError("final Portfolio lost inherited Fink evidence")
    if not any(value.startswith("detection@ztf:lasair") for value in semantic_types):
        raise RuntimeError("final Portfolio did not gain Lasair evidence")

    first_execution_ids = {
        execution.internal_execution_id.value
        for step in first.staged.execution.steps
        for execution in step.executions
    }
    second_execution_ids = {
        execution.internal_execution_id.value
        for step in second.staged.execution.steps[: len(first.staged.execution.steps)]
        for execution in step.executions
    }
    if second_execution_ids != first_execution_ids:
        raise RuntimeError("continuation did not preserve prior physical execution IDs")

    print(f"first-pass provider calls:  {len(calls_before)}")
    print(f"second-pass new calls:      {len(new_calls)}")
    print(f"new call:                   {broker}/{origin}/{endpoint} {params}")
    print(f"final portfolios:           {len(second.portfolios)}")
    print(f"prior execution IDs reused: {len(first_execution_ids)}")
    print("PASS: UI calls stayed simple and middle-layer state stayed DSL-independent")
    print("PASS: second DSL pass filtered prior material and added only new enrichment")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
