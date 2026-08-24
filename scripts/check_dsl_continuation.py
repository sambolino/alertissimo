#!/usr/bin/env python3
"""Prove that a second DSL pass reuses prior provider work and appends new work only."""

from __future__ import annotations

from alertissimo.api import execute_dsl, validate_dsl
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

    print("=== ALERTISSIMO DSL CONTINUATION CHECK ===")
    print("--- first pass ---")
    print(FIRST_PASS.rstrip())
    first = execute_dsl(FIRST_PASS, executor=executor)
    if len(executor.calls) != 2:
        raise RuntimeError(
            f"first pass expected 2 physical calls, observed {len(executor.calls)}"
        )
    if len(first.portfolios) != 1:
        raise RuntimeError(
            f"first pass expected one Portfolio, observed {len(first.portfolios)}"
        )

    print("--- second pass fragment ---")
    print(SECOND_PASS.rstrip())
    validation = validate_dsl(SECOND_PASS, continue_from=first)
    if not validation.is_valid or not validation.is_runnable:
        raise RuntimeError(f"continuation validation failed: {validation!r}")

    calls_before = tuple(executor.calls)
    second = execute_dsl(
        SECOND_PASS,
        continue_from=first,
        executor=executor,
    )

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
    print("PASS: second DSL pass filtered prior material and added only new enrichment")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
