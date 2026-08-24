#!/usr/bin/env python3
"""Live Fink/LSST completeness and cross-execution Portfolio consolidation test.

This preserves the original complex LSST acceptance path independently of the
healthy ZTF fallback in ``live_dsl_complex.py``.  It is expected to report a
provider failure while Fink/LSST is unavailable; when the service is healthy it
verifies classifier-search reuse, late binding, sources+forced-photometry
completeness, and Step-level semantic Portfolio consolidation.
"""

from __future__ import annotations

from dotenv import load_dotenv

from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import compile_surface, parse_surface_script
from alertissimo.orchestration.pipeline import execute_staged_workflow_run
from alertissimo.orchestration.planner import plan_workflow


CLASSIFIER = "stamp_classifier_rubin_beta_20260421"
LSST_SAMPLE_RA = 62.45763123249455
LSST_SAMPLE_DEC = -48.481492749718534
LSST_SAMPLE_RADIUS_ARCSEC = 1.0
DSL = f"""objects from lsst via alerce
    inside ({LSST_SAMPLE_RA}, {LSST_SAMPLE_DEC}, {LSST_SAMPLE_RADIUS_ARCSEC}arcsec)
    where classification@{CLASSIFIER}.best.class = "SN" and classification@{CLASSIFIER}.best.probability >= 0.5
    with classification from {CLASSIFIER}
    with lightcurve via fink
    order by summary.time.last_mjd desc
"""


def object_ids(step_output) -> tuple[str, ...]:
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
    compilation = compile_surface(parse_surface_script(DSL), graph=graph)
    workflow = compilation.workflow
    run = plan_workflow(workflow, graph)

    print("=== PHYSICAL PLAN ===")
    for step_run in run.steps:
        print(f"Semantic Step {step_run.step_index}:")
        for plan_index, plan in enumerate(step_run.endpoint_plans):
            print(
                f"  plan {plan_index}: {plan.broker}/{plan.origin}/{plan.endpoint} "
                f"required={plan.required}"
            )
            print(f"    execution_reuse_from={plan.execution_reuse_from!r}")
            print(f"    candidate_input_from={plan.candidate_input_from!r}")
    print()

    if len(run.steps) != 3:
        raise RuntimeError(f"expected 3 semantic Steps, found {len(run.steps)}")

    search_plan = run.steps[0].endpoint_plans[0]
    classification_plan = run.steps[1].endpoint_plans[0]
    lightcurve_plans = run.steps[2].endpoint_plans

    if classification_plan.execution_reuse_from is None:
        raise RuntimeError("classification Step did not reuse the search execution")
    if len(lightcurve_plans) != 2:
        raise RuntimeError(
            f"expected Fink sources + fp plans, found {len(lightcurve_plans)}"
        )
    if (
        lightcurve_plans[0].broker,
        lightcurve_plans[0].origin,
        lightcurve_plans[0].endpoint,
    ) != ("fink", "lsst", "sources"):
        raise RuntimeError("expected required Fink/LSST sources primary plan")
    if (
        lightcurve_plans[1].broker,
        lightcurve_plans[1].origin,
        lightcurve_plans[1].endpoint,
    ) != ("fink", "lsst", "fp"):
        raise RuntimeError("expected supplementary Fink/LSST fp plan")
    if not lightcurve_plans[0].required or lightcurve_plans[1].required:
        raise RuntimeError("sources must be required and fp supplementary")
    if any(plan.candidate_input_from is None for plan in lightcurve_plans):
        raise RuntimeError("Fink lightcurve plans did not declare candidate input")
    if getattr(workflow.steps[2], "target", None) is not None:
        raise RuntimeError("late-bound Fink target leaked into WorkflowIR")

    registry = EndpointRegistry()
    staged = execute_staged_workflow_run(
        run,
        registry,
        RegistryEndpointExecutor(registry=registry),
        validate_semantic_model=True,
    )

    print("=== PHYSICAL CALLS ===")
    unique_execution_ids: set[str] = set()
    for binding, step_result in zip(staged.bindings, staged.execution.steps):
        print(f"Semantic Step {binding.step_index}:")
        for call in binding.bound_calls:
            plan = call.endpoint_plan
            print(
                f"  {plan.broker}/{plan.origin}/{plan.endpoint} "
                f"required={plan.required} params={dict(call.params)}"
            )
        ids = [execution.internal_execution_id.value for execution in step_result.executions]
        unique_execution_ids.update(ids)
        completed = staged.run.steps[binding.step_index]
        print(f"  execution_ids={ids}")
        print(f"  execution_plan_indexes={list(completed.execution_plan_indexes)}")
        print(f"  vacuous_plan_indexes={list(completed.vacuous_plan_indexes)}")
        for warning in completed.warnings:
            print(f"  WARNING: {warning}")
    print()

    print("=== NORMALIZED OUTPUT ===")
    for step_output in staged.normalized.steps:
        execution_local_count = sum(
            len(execution.portfolios) for execution in step_output.executions
        )
        print(
            f"Semantic Step {step_output.step_index}: "
            f"executions={[execution.execution_id for execution in step_output.executions]} "
            f"execution_local_portfolios={execution_local_count} "
            f"semantic_portfolios={len(step_output.portfolios)} "
            f"object_ids={list(object_ids(step_output))}"
        )
    print()

    print("=== INVARIANTS ===")
    search_ids = set(object_ids(staged.normalized.steps[0]))
    lightcurve_step = staged.normalized.steps[2]
    lightcurve_ids = set(object_ids(lightcurve_step))
    execution_local_count = sum(
        len(execution.portfolios) for execution in lightcurve_step.executions
    )
    semantic_count = len(lightcurve_step.portfolios)

    if not search_ids:
        raise RuntimeError("candidate search produced no semantic object identities")
    missing = search_ids - lightcurve_ids
    if missing:
        raise RuntimeError(
            "Fink lightcurve normalization lost candidate identities: "
            + ", ".join(sorted(missing))
        )
    if semantic_count != len(lightcurve_ids):
        raise RuntimeError(
            "semantic Step Portfolio count does not match positively identified objects: "
            f"semantic={semantic_count}, ids={len(lightcurve_ids)}"
        )

    print("OK: classification reuses the classifier-filtered ALeRCE search")
    print("OK: Fink sources + fp are one semantic GetLightcurveStep")
    print("OK: Fink targets are late-bound while WorkflowIR remains targetless")
    print(f"OK: candidate objects propagated={len(search_ids)}")
    print(f"Execution-local Portfolio occurrences: {execution_local_count}")
    print(f"Semantic Step Portfolios:             {semantic_count}")

    if staged.run.steps[2].warnings:
        print("INCONCLUSIVE: supplementary forced photometry failed; consolidation not exercised")
        return 3
    if len(lightcurve_step.executions) < 2:
        print("INCONCLUSIVE: both physical lightcurve executions were not present")
        return 3
    if execution_local_count <= semantic_count:
        print(
            "INCONCLUSIVE: sources and fp produced no duplicate object Portfolio "
            "occurrences to consolidate in this live sample"
        )
        return 3

    print("OK: cross-execution Portfolio occurrences consolidated by semantic object identity")
    print(f"Unique physical execution IDs observed: {len(unique_execution_ids)}")
    print("Result ordering remains view-only:", compilation.view.model_dump())
    print()
    print("FINK/LSST CONSOLIDATION ACCEPTANCE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
