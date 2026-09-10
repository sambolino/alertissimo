#!/usr/bin/env python3
"""Verify provider object histories as canonical GetLightcurve realizations.

Examples from the repository root::

    PYTHONPATH=. python scripts/live_provider_lightcurves.py --case lasair-lsst
    PYTHONPATH=. python scripts/live_provider_lightcurves.py --case antares-ztf
    PYTHONPATH=. python scripts/live_provider_lightcurves.py --case antares-lsst

Lasair/LSST requires ``LASAIR_LSST_TOKEN``. ANTARES lookups use the public
search client. Each case exercises the complete semantic path: WorkflowIR,
capability selection, target binding, physical execution, and normalization.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv

from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.orchestration.binding import bind_workflow_run
from alertissimo.orchestration.ir import (
    GetLightcurveStep,
    Source,
    TargetSelector,
    WorkflowIR,
)
from alertissimo.orchestration.normalization import normalize_workflow_execution
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import execute_workflow_run


@dataclass(frozen=True)
class Case:
    name: str
    broker: str
    origin: str
    target: str
    expected_endpoint: str
    expects_forced_history: bool
    expects_upper_limits: bool = False


CASES = {
    case.name: case
    for case in (
        Case(
            "lasair-lsst",
            "lasair",
            "lsst",
            "313761042336317573",
            "object",
            True,
        ),
        Case(
            "antares-ztf",
            "antares",
            "ztf",
            "ZTF20aafqubg",
            "get_by_ztf_object_id",
            False,
            True,
        ),
        Case(
            "antares-lsst",
            "antares",
            "lsst",
            "170587117485817955",
            "get_by_lsst_dia_object_id",
            False,
        ),
    )
}


def _upper_limit(point: dict[str, Any]) -> bool | None:
    values = [
        value
        for path, value in point.items()
        if path.startswith("photometry.") and path.endswith(".upper_limit")
    ]
    if len(values) > 1:
        raise RuntimeError("one lightcurve point contains multiple upper-limit flags")
    return values[0] if values else None


def run(case: Case) -> None:
    workflow = WorkflowIR(
        name=f"live {case.name} provider lightcurve",
        steps=[
            GetLightcurveStep(
                target=TargetSelector(ids=[case.target], kind="object"),
                sources=[Source(broker=case.broker, origin=case.origin)],
            )
        ],
    )
    graph = build_capability_graph()
    planned = plan_workflow(workflow, graph)
    plans = planned.steps[0].endpoint_plans
    if len(plans) != 1 or plans[0].endpoint != case.expected_endpoint:
        raise RuntimeError(
            f"unexpected physical realization: {[plan.endpoint for plan in plans]}"
        )

    registry = EndpointRegistry()
    bindings = bind_workflow_run(planned, registry)
    calls = bindings[0].bound_calls
    if len(calls) != 1:
        raise RuntimeError(f"expected one bound call, received {len(calls)}")

    executed = execute_workflow_run(
        planned,
        bindings,
        RegistryEndpointExecutor(registry=registry),
    )
    normalized = normalize_workflow_execution(executed)
    outputs = normalized.steps[0].executions
    portfolios = [portfolio for output in outputs for portfolio in output.portfolios]
    lightcurves = [
        record
        for portfolio in portfolios
        for record in portfolio.records
        if record.semantic_type == f"lightcurve@{case.origin}:{case.broker}"
    ]
    if len(lightcurves) != 1:
        raise RuntimeError(
            f"expected one canonical provider lightcurve, received {len(lightcurves)}"
        )

    fields = dict(lightcurves[0].fields)
    points = list(fields.get("points", ()))
    forced = list(fields.get("forced_photometry_points", ()))
    if not points:
        raise RuntimeError("canonical provider lightcurve contains no ordinary points")
    if case.expects_forced_history and not forced:
        raise RuntimeError("Lasair LSST did not preserve independent forced history")
    if not case.expects_forced_history and forced:
        raise RuntimeError(
            "ANTARES embedded science/template flux was mislabeled as independent forced history"
        )

    upper_limits = sum(_upper_limit(point) is True for point in points)
    detections = sum(_upper_limit(point) is False for point in points)
    if case.expects_upper_limits and (not upper_limits or not detections):
        raise RuntimeError(
            "ANTARES ZTF history did not preserve both detections and upper limits"
        )

    print(f"=== {case.name.upper()} PROVIDER LIGHTCURVE ===")
    print(
        f"physical:   {plans[0].broker}/{plans[0].origin}/{plans[0].endpoint}"
    )
    print(f"params:     {dict(calls[0].params)}")
    print(f"portfolios: {len(portfolios)}")
    print(f"semantic:   {lightcurves[0].semantic_type}")
    print(f"points:     {len(points)}")
    print(f"forced:     {len(forced)}")
    if case.expects_upper_limits:
        print(f"detections: {detections}")
        print(f"limits:     {upper_limits}")
    print(f"PROVIDER LIGHTCURVE ACCEPTANCE PASSED: {case.name}")


def main() -> int:
    # Match the other live entry points: exported credentials take precedence,
    # while repository-local development credentials may come from .env.
    load_dotenv(override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, choices=sorted(CASES))
    args = parser.parse_args()
    run(CASES[args.case])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
