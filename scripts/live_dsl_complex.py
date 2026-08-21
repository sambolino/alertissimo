#!/usr/bin/env python3
"""Live stress test for Alertissimo DSL -> planning -> staged execution -> normalization.

The default acceptance path deliberately avoids the Fink/LSST service.  It uses a
known ZTF cone through Lasair, then late-binds the normalized candidate population
into independent Fink/ZTF and Lasair/ZTF lightcurve retrievals.

Run from the repository root:

    PYTHONPATH=. python scripts/live_dsl_complex.py

Credentials/provider configuration are loaded from the normal Alertissimo
environment/.env.  The Lasair calls require ``LASAIR_ZTF_TOKEN``.
"""

from __future__ import annotations

from dotenv import load_dotenv

from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import compile_surface, parse_surface_script
from alertissimo.orchestration.pipeline import execute_staged_workflow_run
from alertissimo.orchestration.planner import plan_workflow


DSL = """objects from ztf via lasair
    inside (124.87996115142856, -6.0205001, 5arcsec)
    with lightcurve via fink
    with lightcurve via lasair
    order by summary.time.last_mjd desc
"""


def object_ids(step_output) -> tuple[str, ...]:
    """Return primary object identities from the semantic Step Portfolio view."""

    seen: list[str] = []
    for portfolio in step_output.portfolios:
        for record in portfolio.records:
            if record.semantic_type.split("@", 1)[0] != "summary":
                continue
            value = record.fields.get("identity.object_id")
            if value is not None and str(value) not in seen:
                seen.append(str(value))
    return tuple(seen)


def main() -> int:
    load_dotenv(override=False)

    print("=== DSL ===")
    print(DSL.rstrip())
    print()

    graph = build_capability_graph()
    surface = parse_surface_script(DSL)
    compilation = compile_surface(surface, graph=graph)
    workflow = compilation.workflow

    print("=== LOWERED SEMANTIC WORKFLOW ===")
    for index, step in enumerate(workflow.steps):
        print(
            f"Step {index}: op={step.op} "
            f"target={getattr(step, 'target', None)!r} "
            f"sources={[(s.broker, s.origin) for s in getattr(step, 'sources', ())]}"
        )
    print()
    print("Result view:", compilation.view.model_dump())
    print()

    run = plan_workflow(workflow, graph)

    print("=== PHYSICAL PLAN ===")
    for step_run in run.steps:
        print(f"Semantic Step {step_run.step_index}:")
        if not step_run.endpoint_plans:
            print("  (no physical endpoint)")
            continue
        for plan_index, plan in enumerate(step_run.endpoint_plans):
            print(
                f"  plan {plan_index}: "
                f"{plan.broker}/{plan.origin}/{plan.endpoint} "
                f"required={plan.required}"
            )
            print(f"    execution_reuse_from={plan.execution_reuse_from!r}")
            print(f"    candidate_input_from={plan.candidate_input_from!r}")
            if plan.predicate_realization is not None:
                realization = plan.predicate_realization
                print(f"    pushdown={realization.pushdown!r}")
                print(f"    residual={realization.residual!r}")
                print(f"    params={dict(realization.params)}")
    print()

    registry = EndpointRegistry()
    executor = RegistryEndpointExecutor(registry=registry)

    staged = execute_staged_workflow_run(
        run,
        registry,
        executor,
        validate_semantic_model=True,
    )

    print("=== PHYSICAL CALLS ===")
    unique_execution_ids: set[str] = set()
    for binding, step_result in zip(staged.bindings, staged.execution.steps):
        print(f"Semantic Step {binding.step_index}:")
        if not binding.bound_calls:
            print("  (reused/no new physical call)")
        for call in binding.bound_calls:
            plan = call.endpoint_plan
            print(
                f"  {plan.broker}/{plan.origin}/{plan.endpoint} "
                f"required={plan.required} params={dict(call.params)}"
            )
        ids = [
            execution.internal_execution_id.value
            for execution in step_result.executions
        ]
        unique_execution_ids.update(ids)
        print(f"  execution_ids={ids}")
        completed = staged.run.steps[binding.step_index]
        print(f"  execution_plan_indexes={list(completed.execution_plan_indexes)}")
        print(f"  vacuous_plan_indexes={list(completed.vacuous_plan_indexes)}")
        for warning in completed.warnings:
            print(f"  WARNING: {warning}")
    print()

    print("=== NORMALIZED OUTPUT ===")
    for step_output in staged.normalized.steps:
        execution_local_count = sum(
            len(execution.portfolios)
            for execution in step_output.executions
        )
        semantic_count = len(step_output.portfolios)
        execution_ids = [
            execution.execution_id
            for execution in step_output.executions
        ]
        print(
            f"Semantic Step {step_output.step_index}: "
            f"executions={execution_ids} "
            f"execution_local_portfolios={execution_local_count} "
            f"semantic_portfolios={semantic_count} "
            f"object_ids={list(object_ids(step_output))}"
        )

    print()
    print("=== INVARIANTS ===")

    if len(run.steps) != 3:
        raise RuntimeError(f"expected 3 semantic Steps, found {len(run.steps)}")

    search_plans = run.steps[0].endpoint_plans
    fink_plans = run.steps[1].endpoint_plans
    lasair_plans = run.steps[2].endpoint_plans

    if len(search_plans) != 1 or (
        search_plans[0].broker,
        search_plans[0].origin,
        search_plans[0].endpoint,
    ) != ("lasair", "ztf", "cone"):
        raise RuntimeError("expected Step 0 to plan lasair/ztf/cone")

    if len(fink_plans) != 1 or (
        fink_plans[0].broker,
        fink_plans[0].origin,
        fink_plans[0].endpoint,
    ) != ("fink", "ztf", "objects"):
        raise RuntimeError("expected Step 1 to plan fink/ztf/objects")

    if len(lasair_plans) != 1 or (
        lasair_plans[0].broker,
        lasair_plans[0].origin,
        lasair_plans[0].endpoint,
    ) != ("lasair", "ztf", "lightcurves"):
        raise RuntimeError("expected Step 2 to plan lasair/ztf/lightcurves")

    if fink_plans[0].candidate_input_from is None:
        raise RuntimeError("Fink/ZTF lightcurve Step did not declare runtime candidate input")
    if lasair_plans[0].candidate_input_from is None:
        raise RuntimeError("Lasair/ZTF lightcurve Step did not declare runtime candidate input")

    if getattr(workflow.steps[1], "target", None) is not None:
        raise RuntimeError("late-bound Fink target leaked into semantic WorkflowIR")
    if getattr(workflow.steps[2], "target", None) is not None:
        raise RuntimeError("late-bound Lasair target leaked into semantic WorkflowIR")

    search_ids = set(object_ids(staged.normalized.steps[0]))
    fink_ids = set(object_ids(staged.normalized.steps[1]))
    lasair_ids = set(object_ids(staged.normalized.steps[2]))

    if not search_ids:
        raise RuntimeError("Lasair cone search produced no semantic object identities")

    missing_fink = search_ids - fink_ids
    if missing_fink:
        raise RuntimeError(
            "Fink/ZTF normalization lost candidate identities: "
            + ", ".join(sorted(missing_fink))
        )

    missing_lasair = search_ids - lasair_ids
    if missing_lasair:
        raise RuntimeError(
            "Lasair/ZTF normalization lost candidate identities: "
            + ", ".join(sorted(missing_lasair))
        )

    if len(unique_execution_ids) != 3:
        raise RuntimeError(
            f"expected 3 unique physical executions, found {len(unique_execution_ids)}"
        )

    print("OK: 3 semantic Steps")
    print("OK: Lasair/ZTF cone search creates the candidate population")
    print("OK: Fink/ZTF lightcurve target is late-bound from candidate identities")
    print("OK: Lasair/ZTF lightcurve target is late-bound from the same candidates")
    print("OK: both downstream WorkflowIR targets remain None")
    print(
        f"OK: {len(search_ids)} candidate object(s) propagated independently into "
        "both downstream providers"
    )
    print("OK: semantic Step Portfolio views expose the normalized object identities")
    print(f"Unique physical execution IDs observed: {len(unique_execution_ids)}")
    print("Result ordering remains view-only:", compilation.view.model_dump())
    print(
        "NOTE: this ZTF fallback uses one physical execution per lightcurve Step; "
        "it validates the semantic Portfolio view but does not exercise the "
        "cross-execution sources+forced-photometry consolidation case."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
