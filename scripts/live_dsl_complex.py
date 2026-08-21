#!/usr/bin/env python3
"""Live stress test for Alertissimo DSL -> planning -> staged execution -> normalization.

Run from the repository root:

    PYTHONPATH=. python scripts/live_dsl_complex.py

Credentials/provider configuration are loaded from the normal Alertissimo environment/.env.
"""

from __future__ import annotations

from dotenv import load_dotenv

from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import compile_surface, parse_surface_script
from alertissimo.orchestration.pipeline import execute_staged_workflow_run
from alertissimo.orchestration.planner import plan_workflow


CLASSIFIER = "stamp_classifier_rubin_beta_20260421"

DSL = f"""objects from lsst via alerce
    where classification@{CLASSIFIER}.best.class = "SN" and classification@{CLASSIFIER}.best.probability >= 0.5
    with classification from {CLASSIFIER}
    with lightcurve via fink
    order by summary.time.last_mjd desc
"""


def object_ids(step_output) -> tuple[str, ...]:
    seen: list[str] = []
    for execution in step_output.executions:
        for portfolio in execution.portfolios:
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
            print(
                f"    execution_reuse_from={plan.execution_reuse_from!r}"
            )
            print(
                f"    candidate_input_from={plan.candidate_input_from!r}"
            )
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
        for warning in completed.warnings:
            print(f"  WARNING: {warning}")
    print()

    print("=== NORMALIZED OUTPUT ===")
    for step_output in staged.normalized.steps:
        portfolio_count = sum(
            len(execution.portfolios)
            for execution in step_output.executions
        )
        execution_ids = [
            execution.execution_id
            for execution in step_output.executions
        ]
        print(
            f"Semantic Step {step_output.step_index}: "
            f"executions={execution_ids} "
            f"portfolios={portfolio_count} "
            f"object_ids={list(object_ids(step_output))}"
        )

    print()
    print("=== INVARIANTS ===")

    if len(run.steps) != 3:
        raise RuntimeError(f"expected 3 semantic Steps, found {len(run.steps)}")

    search_plan = run.steps[0].endpoint_plans[0]
    classification_plan = run.steps[1].endpoint_plans[0]
    lightcurve_plans = run.steps[2].endpoint_plans
    lightcurve_plan = lightcurve_plans[0]

    if classification_plan.execution_reuse_from is None:
        raise RuntimeError(
            "classification Step did not reuse the classifier-filtered search execution"
        )

    if lightcurve_plan.candidate_input_from is None:
        raise RuntimeError(
            "Fink lightcurve Step did not declare runtime candidate input"
        )

    if len(lightcurve_plans) != 2:
        raise RuntimeError(
            f"expected primary + forced lightcurve plans, found {len(lightcurve_plans)}"
        )
    if not lightcurve_plans[0].required or lightcurve_plans[1].required:
        raise RuntimeError(
            "lightcurve completeness policy is wrong: sources must be required and fp supplementary"
        )

    if getattr(workflow.steps[2], "target", None) is not None:
        raise RuntimeError(
            "late-bound Fink target leaked into semantic WorkflowIR"
        )

    search_ids = set(object_ids(staged.normalized.steps[0]))
    lightcurve_ids = set(object_ids(staged.normalized.steps[2]))

    if not search_ids:
        raise RuntimeError("candidate search produced no semantic object identities")

    missing = search_ids - lightcurve_ids
    if missing:
        raise RuntimeError(
            "Fink lightcurve normalization lost candidate identities: "
            + ", ".join(sorted(missing))
        )

    print("OK: 3 semantic Steps")
    print(
        "OK: classification reuses "
        f"{search_plan.broker}/{search_plan.origin}/{search_plan.endpoint}"
    )
    print("OK: Fink lightcurve target is late-bound from candidate identities")
    print("OK: Fink sources is required and forced photometry is supplementary")
    print("OK: WorkflowIR lightcurve target remains None")
    print(
        f"OK: {len(search_ids)} candidate object(s) propagated into Fink normalization"
    )
    if staged.run.steps[2].warnings:
        print(
            "OK: supplementary failure was retained as a warning without failing "
            "the lightcurve Step"
        )
    print(f"Unique physical execution IDs observed: {len(unique_execution_ids)}")
    print("Result ordering remains view-only:", compilation.view.model_dump())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
