#!/usr/bin/env python3
"""Exercise an explicit-ID DSL lookup and a second UI continuation call.

Run from the repository root::

    PYTHONPATH=. python scripts/live_dsl_lookup.py

The first call establishes the active generic WorkflowIR from a known object ID.
The second call appends ``GetLightcurveStep`` to that IR and must reuse the lookup
execution because the ANTARES object response already realizes the lightcurve.
"""

from __future__ import annotations

from typing import Any

from dotenv import load_dotenv

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor
from alertissimo.orchestration.ir import LookupStep


TARGET = "ZTF20aafqubg"
FIRST_DSL = f"object {TARGET} from ztf via antares\n"
SECOND_DSL = "with lightcurve via antares\n"


class RecordingExecutor:
    def __init__(self, registry: EndpointRegistry) -> None:
        self.delegate = RegistryEndpointExecutor(registry=registry)
        self.calls: list[tuple[str, str, str, dict[str, Any]]] = []

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        supplied = dict(params or {})
        self.calls.append((broker, origin, endpoint, supplied))
        return self.delegate.execute(
            broker=broker,
            origin=origin,
            endpoint=endpoint,
            params=supplied,
            headers=headers,
        )


def _require_runnable(source: str) -> None:
    validation = validate_dsl(source)
    if not validation.is_runnable:
        raise RuntimeError(
            "DSL validation failed: "
            f"{validation.parse_error or validation.lowering_error or validation.semantic}"
        )


def main() -> int:
    load_dotenv(override=False)
    registry = EndpointRegistry()
    executor = RecordingExecutor(registry)

    _require_runnable(FIRST_DSL)
    first = execute_dsl(FIRST_DSL, registry=registry, executor=executor)
    if len(first.workflow.steps) != 1 or not isinstance(
        first.workflow.steps[0], LookupStep
    ):
        raise RuntimeError("first DSL call did not lower to exactly one LookupStep")
    lookup = first.workflow.steps[0]
    if lookup.target.kind != "object" or lookup.target.ids != [TARGET]:
        raise RuntimeError(f"lookup target changed during lowering: {lookup.target}")
    if len(executor.calls) != 1:
        raise RuntimeError(
            f"object lookup expected one physical call, received {len(executor.calls)}"
        )

    _require_runnable(SECOND_DSL)
    second = execute_dsl(SECOND_DSL, registry=registry, executor=executor)
    if [step.op for step in second.workflow.steps] != ["lookup", "get_lightcurve"]:
        raise RuntimeError("continuation did not extend the active WorkflowIR")
    if len(executor.calls) != 1:
        raise RuntimeError("continuation re-executed or added unnecessary provider work")
    if second.run.steps[1].execution_ids != first.run.steps[0].execution_ids:
        raise RuntimeError("GetLightcurve did not reuse the lookup execution identity")

    lightcurves = [
        record
        for portfolio in second.portfolios
        for record in portfolio.records
        if record.semantic_type == "lightcurve@ztf:antares"
    ]
    if len(lightcurves) != 1:
        raise RuntimeError(
            f"expected one canonical ANTARES lightcurve, received {len(lightcurves)}"
        )
    points = list(dict(lightcurves[0].fields).get("points", ()))
    if not points:
        raise RuntimeError("canonical lookup lightcurve contains no points")

    print("=== ALERTISSIMO DSL OBJECT LOOKUP ===")
    print("--- first UI call ---")
    print(FIRST_DSL.rstrip())
    print("--- second UI call ---")
    print(SECOND_DSL.rstrip())
    print(f"physical calls:       {len(executor.calls)}")
    print(
        "physical endpoint:    "
        f"{executor.calls[0][0]}/{executor.calls[0][1]}/{executor.calls[0][2]}"
    )
    print(f"lookup target kind:   {lookup.target.kind}")
    print(f"lookup target IDs:    {lookup.target.ids}")
    print(f"lightcurve points:    {len(points)}")
    print(f"execution IDs reused: {second.run.steps[1].execution_ids}")
    print("LIVE DSL LOOKUP ACCEPTANCE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
