#!/usr/bin/env python3
"""Verify that one Lasair/ZTF cone Step also materializes compact summaries.

Run from the repository root::

    PYTHONPATH=. python scripts/live_dsl_lasair_summary.py
    PYTHONPATH=. python scripts/live_dsl_lasair_summary.py --plan-only
"""

from __future__ import annotations

import argparse
import re

from dotenv import load_dotenv

from alertissimo.api import execute_dsl
from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import compile_surface_to_ir, parse_surface_script
from alertissimo.orchestration.normalization import summary_object_identity
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import PlanCandidateInputRef


DEFAULT_RA = 124.87996115142856
DEFAULT_DEC = -6.0205001
DEFAULT_RADIUS_ARCSEC = 5.0
EXPECTED_PROJECTION = (
    "objects.objectId,objects.ramean,objects.decmean,objects.ncand,"
    "objects.jdmin,objects.jdmax"
)
RICH_FIELDS = {
    "identity.object_id",
    "position.ra",
    "position.dec",
    "detection_count",
    "time.first_mjd",
    "time.last_mjd",
}


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ra", type=float, default=DEFAULT_RA)
    parser.add_argument("--dec", type=float, default=DEFAULT_DEC)
    parser.add_argument("--radius-arcsec", type=float, default=DEFAULT_RADIUS_ARCSEC)
    parser.add_argument("--plan-only", action="store_true")
    return parser.parse_args()


def _assert_plan(workflow, run) -> None:
    if len(workflow.steps) != 1 or workflow.steps[0].op != "cone_search":
        raise RuntimeError("expected exactly one semantic cone_search Step")
    plans = run.steps[0].endpoint_plans
    actual = [(plan.broker, plan.origin, plan.endpoint) for plan in plans]
    expected = [("lasair", "ztf", "cone"), ("lasair", "ztf", "query")]
    if actual != expected:
        raise RuntimeError(f"unexpected physical plan: {actual!r}")
    if plans[1].candidate_input_from_plan != PlanCandidateInputRef(plan_index=0):
        raise RuntimeError("compact query is not bound from the cone plan's candidates")
    if plans[1].required:
        raise RuntimeError("compact query must remain supplementary")
    expected_params = {
        "selected": EXPECTED_PROJECTION,
        "tables": "objects",
        "limit": 100,
        "offset": 0,
    }
    if plans[1].request_params != expected_params:
        raise RuntimeError(
            f"unexpected compact query projection: {plans[1].request_params!r}"
        )


def main() -> int:
    load_dotenv(override=False)
    args = _args()
    if not 0.0 <= args.ra < 360.0:
        raise SystemExit("--ra must be in [0, 360)")
    if not -90.0 <= args.dec <= 90.0:
        raise SystemExit("--dec must be in [-90, 90]")
    if args.radius_arcsec <= 0.0:
        raise SystemExit("--radius-arcsec must be positive")

    dsl = f"""objects from ztf via lasair
inside ({args.ra}, {args.dec}, {args.radius_arcsec}arcsec)
"""
    graph = build_capability_graph()
    workflow = compile_surface_to_ir(
        parse_surface_script(dsl),
        graph=graph,
        name="live Lasair compact cone summary",
    )
    planned = plan_workflow(workflow, graph)
    _assert_plan(workflow, planned)

    print("=== DSL ===")
    print(dsl.rstrip())
    print("semantic Steps: 1")
    print("physical plans: lasair/ztf/cone -> lasair/ztf/query (supplementary)")
    if args.plan_only:
        print("LASAIR COMPACT CONE SUMMARY PLAN PASSED")
        return 0

    registry = EndpointRegistry()
    execution = execute_dsl(
        dsl,
        name="live Lasair compact cone summary",
        graph=graph,
        registry=registry,
        executor=RegistryEndpointExecutor(registry=registry),
    )
    _assert_plan(execution.workflow, execution.run)

    step_run = execution.run.steps[0]
    if step_run.warnings:
        raise RuntimeError(f"supplementary query warning(s): {step_run.warnings!r}")
    calls = execution.staged.bindings[0].bound_calls
    query_calls = [call for call in calls if call.endpoint_plan.endpoint == "query"]
    if not query_calls:
        raise RuntimeError("Lasair compact query was not physically bound")
    for call in query_calls:
        if call.params.get("selected") != EXPECTED_PROJECTION:
            raise RuntimeError(f"query used an unexpected projection: {call.params!r}")

    identities = {
        identity[1]
        for portfolio in execution.portfolios
        if (identity := summary_object_identity(portfolio)) is not None
    }
    bound_ids = {
        value
        for call in query_calls
        for value in re.findall(r'"(ZTF\d{2}[a-z]{7})"', call.params["conditions"])
    }
    if not identities:
        raise RuntimeError("live cone returned no normalized object identities")
    if bound_ids != identities:
        raise RuntimeError(
            "compact query targets differ from normalized cone candidates: "
            f"cone={sorted(identities)!r} query={sorted(bound_ids)!r}"
        )

    rich_ids: set[str] = set()
    detection_counts: dict[str, int] = {}
    for portfolio in execution.portfolios:
        for record in portfolio.records:
            if record.semantic_type != "summary@ztf:lasair":
                continue
            fields = record.fields
            if RICH_FIELDS.issubset(fields):
                object_id = str(fields["identity.object_id"])
                rich_ids.add(object_id)
                detection_counts[object_id] = int(fields["detection_count"])
    if rich_ids != identities:
        raise RuntimeError(
            "not every cone candidate received a compact semantic summary: "
            f"missing={sorted(identities - rich_ids)!r}"
        )

    physical = [
        execution_result.execution_provenance.endpoint
        for execution_result in execution.staged.execution.steps[0].executions
    ]
    print(f"physical executions: {physical!r}")
    print(f"semantic portfolios: {len(execution.portfolios)}")
    print(f"compact summaries:   {len(rich_ids)}")
    print(f"reported detections: {dict(sorted(detection_counts.items()))!r}")
    print("OK: query targets exactly the normalized cone candidate set")
    print("OK: every Portfolio exposes position, reported count, and first/last MJD")
    print("LASAIR COMPACT CONE SUMMARY ACCEPTANCE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
