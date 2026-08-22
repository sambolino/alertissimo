#!/usr/bin/env python3
"""Live Search -> Get evidence -> Filter -> downstream Get acceptance.

The scenario is the live counterpart of ``test_dsl_filter_candidate_flow``:

    objects from ztf via lasair
        inside (...)
        with lightcurve via fink
        filter detection@ztf:fink.quality.real_bogus >= <threshold>
        with lightcurve via lasair

The local FilterStep must own no provider endpoint, must consume the materialized
Fink semantic view, and the downstream Lasair call must bind only surviving
candidate identities. Live data may legitimately make the selection empty or
unchanged; those cases are reported INCONCLUSIVE rather than as architecture
failures.
"""

from __future__ import annotations

import argparse

from dotenv import load_dotenv

from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import compile_surface_to_ir, parse_surface_script
from alertissimo.orchestration.pipeline import execute_staged_workflow_run
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import CandidateInputRef


DEFAULT_RA = 124.87996115142856
DEFAULT_DEC = -6.0205001
DEFAULT_RADIUS_ARCSEC = 300.0
DEFAULT_THRESHOLD = 0.8


def _object_ids(step_output) -> tuple[str, ...]:
    found: list[str] = []
    for portfolio in step_output.portfolios:
        values = {
            str(value)
            for record in portfolio.records
            if record.semantic_type.split("@", 1)[0] == "summary"
            for key, value in record.fields.items()
            if key == "identity.object_id" and value is not None
        }
        if len(values) > 1:
            raise RuntimeError(
                f"Portfolio has ambiguous primary object identity: {sorted(values)!r}"
            )
        if values:
            value = next(iter(values))
            if value not in found:
                found.append(value)
    return tuple(found)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ra", type=float, default=DEFAULT_RA)
    parser.add_argument("--dec", type=float, default=DEFAULT_DEC)
    parser.add_argument("--radius-arcsec", type=float, default=DEFAULT_RADIUS_ARCSEC)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--plan-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    load_dotenv(override=False)

    dsl = f"""objects from ztf via lasair
    inside ({args.ra}, {args.dec}, {args.radius_arcsec}arcsec)
    with lightcurve via fink
    filter detection@ztf:fink.quality.real_bogus >= {args.threshold}
    with lightcurve via lasair
"""

    print("=== DSL ===")
    print(dsl.rstrip())
    print()

    graph = build_capability_graph()
    workflow = compile_surface_to_ir(
        parse_surface_script(dsl),
        graph=graph,
        name="live filter candidate flow",
    )
    run = plan_workflow(workflow, graph)

    print("=== PHYSICAL PLAN ===")
    for step_run in run.steps:
        print(f"Semantic Step {step_run.step_index}: op={workflow.steps[step_run.step_index].op}")
        if not step_run.endpoint_plans:
            print("  (local/no provider endpoint)")
        for plan_index, plan in enumerate(step_run.endpoint_plans):
            print(
                f"  plan {plan_index}: {plan.broker}/{plan.origin}/{plan.endpoint} "
                f"candidate_input_from={plan.candidate_input_from!r}"
            )
        if step_run.candidate_input_from is not None:
            print(f"  step candidate_input_from={step_run.candidate_input_from!r}")
    print()

    if [step.op for step in workflow.steps] != [
        "cone_search",
        "get_lightcurve",
        "filter",
        "get_lightcurve",
    ]:
        raise RuntimeError(
            f"unexpected semantic workflow: {[step.op for step in workflow.steps]!r}"
        )

    if len(run.steps[1].endpoint_plans) != 1:
        raise RuntimeError("expected one Fink/ZTF evidence plan")
    evidence_plan = run.steps[1].endpoint_plans[0]
    if (
        evidence_plan.broker,
        evidence_plan.origin,
        evidence_plan.endpoint,
    ) != ("fink", "ztf", "objects"):
        raise RuntimeError("expected Fink/ZTF objects as filter evidence")
    if evidence_plan.candidate_input_from != CandidateInputRef(step_index=0):
        raise RuntimeError("Fink evidence is not bound from search candidates")

    filter_run = run.steps[2]
    if filter_run.endpoint_plans:
        raise RuntimeError("FilterStep fabricated a provider endpoint")
    if filter_run.candidate_input_from != CandidateInputRef(step_index=1):
        raise RuntimeError("FilterStep does not consume the Fink materialized view")

    if len(run.steps[3].endpoint_plans) != 1:
        raise RuntimeError("expected one downstream Lasair plan")
    downstream_plan = run.steps[3].endpoint_plans[0]
    if (
        downstream_plan.broker,
        downstream_plan.origin,
        downstream_plan.endpoint,
    ) != ("lasair", "ztf", "lightcurves"):
        raise RuntimeError("expected Lasair/ZTF lightcurves downstream")
    if downstream_plan.candidate_input_from != CandidateInputRef(step_index=2):
        raise RuntimeError("downstream Lasair plan does not bind Filter survivors")

    print("OK: Search -> Fink evidence -> local Filter -> Lasair downstream planned")
    print("OK: Filter owns no physical endpoint")
    print("OK: candidate dependency chain is occurrence-aligned")
    print()

    if args.plan_only:
        print("Plan-only mode: no provider APIs contacted.")
        return 0

    registry = EndpointRegistry()
    staged = execute_staged_workflow_run(
        run,
        registry,
        RegistryEndpointExecutor(registry=registry),
        validate_semantic_model=True,
    )

    print("=== PHYSICAL CALLS ===")
    for binding in staged.bindings:
        print(f"Semantic Step {binding.step_index}:")
        if not binding.bound_calls:
            print("  (none)")
        for call in binding.bound_calls:
            plan = call.endpoint_plan
            print(
                f"  {plan.broker}/{plan.origin}/{plan.endpoint} "
                f"params={dict(call.params)}"
            )
    print()

    before_ids = _object_ids(staged.normalized.steps[1])
    survivor_ids = _object_ids(staged.normalized.steps[2])
    downstream_ids = _object_ids(staged.normalized.steps[3])

    print("=== CANDIDATE FLOW ===")
    print(f"Fink materialized candidates: {len(before_ids)} {list(before_ids)}")
    print(f"Filter survivors:             {len(survivor_ids)} {list(survivor_ids)}")
    print(f"Lasair normalized objects:    {len(downstream_ids)} {list(downstream_ids)}")
    print()

    if staged.run.steps[2].execution_ids:
        raise RuntimeError("local FilterStep fabricated a physical execution")
    if not set(survivor_ids).issubset(before_ids):
        raise RuntimeError("Filter introduced candidate identities not present in its input")

    downstream_calls = staged.bindings[3].bound_calls
    if not survivor_ids:
        if downstream_calls:
            raise RuntimeError("empty Filter result still invoked downstream provider")
        if staged.run.steps[3].execution_ids:
            raise RuntimeError("empty downstream candidate set fabricated an execution")
        print("OK: empty Filter result made downstream Get vacuous")
        print("INCONCLUSIVE: live filter selected zero objects; non-empty survivor binding not exercised")
        return 3

    if len(downstream_calls) != 1:
        raise RuntimeError(
            f"expected one downstream Lasair call for survivors, got {len(downstream_calls)}"
        )

    bound = downstream_calls[0].params.get("objectIds")
    bound_ids = tuple(str(bound).split(",")) if bound else ()
    if set(bound_ids) != set(survivor_ids):
        raise RuntimeError(
            "downstream Lasair binding differs from Filter survivors: "
            f"bound={list(bound_ids)!r}, survivors={list(survivor_ids)!r}"
        )
    if set(downstream_ids) != set(survivor_ids):
        raise RuntimeError(
            "downstream normalization differs from Filter survivors: "
            f"normalized={list(downstream_ids)!r}, survivors={list(survivor_ids)!r}"
        )

    print("OK: downstream target binding equals the Filter survivor set")
    print("OK: downstream normalization preserves the survivor identities")

    if set(survivor_ids) == set(before_ids):
        print("INCONCLUSIVE: live filter kept every candidate; narrowing was not exercised")
        return 3

    print(f"OK: Filter narrowed candidates from {len(before_ids)} to {len(survivor_ids)}")
    print()
    print("FILTER CANDIDATE-FLOW ACCEPTANCE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
