#!/usr/bin/env python3
"""Live LSST+ZTF multisurvey discovery acceptance using ALeRCE.

This intentionally avoids Fink/LSST while that service is unavailable.

It tests one semantic cone-search Step spanning both survey namespaces:

    objects from lsst, ztf via alerce
        inside (<ra>, <dec>, <radius>arcsec)

Expected physical realization:

    one semantic cone_search
        -> alerce/lsst/query_objects
        -> alerce/ztf/query_objects

The default coordinate is a live-proven overlap field that returned normalized
objects from both ALeRCE LSST and ALeRCE ZTF on 2026-08-21.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from typing import Any, Iterable

from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import compile_surface_to_ir, parse_surface_script
from alertissimo.orchestration.normalization import normalize_execution
from alertissimo.orchestration.pipeline import execute_staged_workflow_run
from alertissimo.orchestration.planner import plan_workflow


DEFAULT_RA = 305.5822327501884
DEFAULT_DEC = -18.7909207179724
DEFAULT_RADIUS_ARCSEC = 300.0


def _summary_object_ids(portfolios: Iterable[Any]) -> tuple[str, ...]:
    seen: list[str] = []
    for portfolio in portfolios:
        for record in portfolio.records:
            if record.semantic_type.split("@", 1)[0] != "summary":
                continue
            value = record.fields.get("identity.object_id")
            if value is None:
                continue
            text = str(value)
            if text not in seen:
                seen.append(text)
    return tuple(seen)


def _candidate_ids_by_origin(step_result) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for execution in step_result.executions:
        provenance = execution.execution_provenance
        portfolios = normalize_execution(execution)
        for object_id in _summary_object_ids(portfolios):
            if object_id not in grouped[provenance.origin]:
                grouped[provenance.origin].append(object_id)
    return {origin: tuple(values) for origin, values in grouped.items()}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run live LSST+ZTF cone discovery through ALeRCE and verify "
            "origin-preserving normalization."
        )
    )
    parser.add_argument("--ra", type=float, default=DEFAULT_RA)
    parser.add_argument("--dec", type=float, default=DEFAULT_DEC)
    parser.add_argument("--radius-arcsec", type=float, default=DEFAULT_RADIUS_ARCSEC)
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="compile and plan only; do not contact providers",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not (0.0 <= args.ra < 360.0):
        raise SystemExit("--ra must be in [0, 360)")
    if not (-90.0 <= args.dec <= 90.0):
        raise SystemExit("--dec must be in [-90, 90]")
    if args.radius_arcsec <= 0:
        raise SystemExit("--radius-arcsec must be positive")

    dsl = f"""objects from lsst, ztf via alerce
    inside ({args.ra}, {args.dec}, {args.radius_arcsec}arcsec)
"""

    print("=== DSL ===")
    print(dsl.rstrip())
    print()

    graph = build_capability_graph()
    surface = parse_surface_script(dsl)
    workflow = compile_surface_to_ir(
        surface,
        graph=graph,
        name="live alerce multisurvey discovery",
    )

    print("=== LOWERED SEMANTIC WORKFLOW ===")
    for index, step in enumerate(workflow.steps):
        print(
            f"Step {index}: op={step.op} "
            f"target={getattr(step, 'target', None)!r} "
            f"sources={[(s.broker, s.origin) for s in step.sources]}"
        )
    print()

    run = plan_workflow(workflow, graph)

    print("=== PHYSICAL PLAN ===")
    for step_run in run.steps:
        print(f"Semantic Step {step_run.step_index}:")
        for plan_index, plan in enumerate(step_run.endpoint_plans):
            print(
                f"  plan {plan_index}: "
                f"{plan.broker}/{plan.origin}/{plan.endpoint} "
                f"required={plan.required}"
            )
            print(f"    execution_reuse_from={plan.execution_reuse_from!r}")
            print(f"    candidate_input_from={plan.candidate_input_from!r}")
    print()

    print("=== PRE-LIVE INVARIANTS ===")
    if len(workflow.steps) != 1:
        raise RuntimeError(f"expected 1 semantic Step, got {len(workflow.steps)}")
    if workflow.steps[0].op != "cone_search":
        raise RuntimeError(f"expected cone_search, got {workflow.steps[0].op}")

    expected_plans = {
        ("alerce", "lsst", "query_objects"),
        ("alerce", "ztf", "query_objects"),
    }
    actual_plans = {
        (plan.broker, plan.origin, plan.endpoint)
        for plan in run.steps[0].endpoint_plans
    }
    if actual_plans != expected_plans:
        raise RuntimeError(
            f"unexpected multisurvey physical plan: {sorted(actual_plans)!r}"
        )
    if getattr(workflow.steps[0], "target", None) is not None:
        raise RuntimeError("candidate search unexpectedly acquired a target")

    print("OK: one semantic cone_search Step")
    print("OK: ALeRCE LSST + ZTF query_objects selected")
    print("OK: WorkflowIR target remains None")
    print()

    if args.plan_only:
        print("Plan-only mode: no provider APIs contacted.")
        return 0

    registry = EndpointRegistry()
    executor = RegistryEndpointExecutor(registry=registry)
    staged = execute_staged_workflow_run(
        run,
        registry,
        executor,
        validate_semantic_model=True,
    )

    print("=== PHYSICAL CALLS ===")
    for binding, step_result in zip(staged.bindings, staged.execution.steps):
        print(f"Semantic Step {binding.step_index}:")
        for call in binding.bound_calls:
            plan = call.endpoint_plan
            print(
                f"  {plan.broker}/{plan.origin}/{plan.endpoint} "
                f"required={plan.required} params={dict(call.params)}"
            )
        print(
            "  execution_ids="
            + repr([e.internal_execution_id.value for e in step_result.executions])
        )
    print()

    grouped = _candidate_ids_by_origin(staged.execution.steps[0])

    print("=== NORMALIZED SEARCH CANDIDATES BY ORIGIN ===")
    for origin in ("lsst", "ztf"):
        ids = grouped.get(origin, ())
        print(f"{origin}: {len(ids)} candidate(s) {list(ids)}")
    print()

    step = staged.normalized.steps[0]
    execution_local_count = sum(
        len(execution.portfolios) for execution in step.executions
    )

    print("=== NORMALIZED OUTPUT ===")
    print(
        f"Semantic Step 0: "
        f"executions={[execution.execution_id for execution in step.executions]} "
        f"execution_local_portfolios={execution_local_count} "
        f"semantic_portfolios={len(step.portfolios)}"
    )
    print()

    print("=== INVARIANTS ===")
    completed_origins = {
        execution.execution_provenance.origin
        for execution in staged.execution.steps[0].executions
    }
    if completed_origins != {"lsst", "ztf"}:
        raise RuntimeError(
            f"did not execute both ALeRCE survey plans: {sorted(completed_origins)!r}"
        )

    print("OK: ALeRCE LSST physical search executed")
    print("OK: ALeRCE ZTF physical search executed")
    print("OK: execution provenance preserves survey origin")

    if not grouped.get("lsst") or not grouped.get("ztf"):
        missing = [origin for origin in ("lsst", "ztf") if not grouped.get(origin)]
        print(
            "INCONCLUSIVE: live data did not produce candidates "
            f"from both surveys; missing={missing}"
        )
        print("Try a different field or increase --radius-arcsec.")
        return 3

    print(f"OK: LSST candidates={len(grouped['lsst'])}")
    print(f"OK: ZTF candidates={len(grouped['ztf'])}")
    print("OK: both survey namespaces coexist in one semantic Step")
    print()
    print("MULTI-SURVEY DISCOVERY ACCEPTANCE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
