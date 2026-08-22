#!/usr/bin/env python3
"""Live Search -> Match -> downstream GetLightcurve candidate propagation acceptance.

This script exercises the behavior that a terminal Match-only smoke test cannot:
MatchStep is a relational filter, so a later targetless provider retrieval must bind
only the identities that survive Match, not the earlier Search population.

The literal DSL is::

    objects from lsst, ztf via alerce
    inside (<ra>, <dec>, <search radius>)
    match on position inside <match radius>
    with lightcurve via fink

ALeRCE performs the live LSST+ZTF discovery. MatchStep executes locally over
normalized semantic positions. Fink/ZTF then receives only the matched ZTF
identities, because a Fink/ZTF endpoint cannot consume LSST object IDs.
"""

from __future__ import annotations

import argparse
from collections import Counter

from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import compile_surface_to_ir, parse_surface_script
from alertissimo.orchestration.ir import MatchStep
from alertissimo.orchestration.local_semantics import finalize_local_semantics
from alertissimo.orchestration.normalization import summary_object_identity
from alertissimo.orchestration.pipeline import execute_staged_workflow_run
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import StepRunState


DEFAULT_RA = 150.1245220572
DEFAULT_DEC = 0.8775815301
DEFAULT_SEARCH_RADIUS_ARCSEC = 5.0
DEFAULT_MATCH_RADIUS_ARCSEC = 1.0


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run live ALeRCE LSST+ZTF discovery, local positional MatchStep, then "
            "verify that Fink lightcurve retrieval receives only matched ZTF IDs."
        )
    )
    parser.add_argument("--ra", type=float, default=DEFAULT_RA)
    parser.add_argument("--dec", type=float, default=DEFAULT_DEC)
    parser.add_argument(
        "--search-radius-arcsec", type=float, default=DEFAULT_SEARCH_RADIUS_ARCSEC
    )
    parser.add_argument(
        "--match-radius-arcsec", type=float, default=DEFAULT_MATCH_RADIUS_ARCSEC
    )
    parser.add_argument(
        "--expect-lsst-id",
        help="Require this LSST identity to survive Match.",
    )
    parser.add_argument(
        "--expect-ztf-id",
        help="Require this ZTF identity to survive Match and propagate to Fink.",
    )
    parser.add_argument("--plan-only", action="store_true")
    return parser.parse_args()


def _identity_set(step_view) -> set[tuple[str, str]]:
    identities = set()
    for portfolio in step_view.portfolios:
        identity = summary_object_identity(portfolio)
        if identity is not None:
            identities.add((str(identity[0]), str(identity[1])))
    return identities


def _csv_ids(value) -> tuple[str, ...]:
    if not isinstance(value, str):
        raise RuntimeError(
            "Fink/ZTF objects binding did not materialize objectId as a CSV string: "
            f"{value!r}"
        )
    values = tuple(item.strip() for item in value.split(",") if item.strip())
    if len(values) != len(set(values)):
        raise RuntimeError(f"downstream objectId binding contains duplicates: {values!r}")
    return values


def main() -> int:
    args = _args()
    if not 0.0 <= args.ra < 360.0:
        raise SystemExit("--ra must be in [0, 360)")
    if not -90.0 <= args.dec <= 90.0:
        raise SystemExit("--dec must be in [-90, 90]")
    if args.search_radius_arcsec <= 0.0 or args.match_radius_arcsec <= 0.0:
        raise SystemExit("search and match radii must be positive")
    if bool(args.expect_lsst_id) != bool(args.expect_ztf_id):
        raise SystemExit("--expect-lsst-id and --expect-ztf-id must be supplied together")

    dsl = f"""objects from lsst, ztf via alerce
inside ({args.ra}, {args.dec}, {args.search_radius_arcsec}arcsec)
match on position inside {args.match_radius_arcsec}arcsec
with lightcurve via fink
"""
    print("=== DSL ===")
    print(dsl.rstrip())
    print()

    graph = build_capability_graph()
    workflow = compile_surface_to_ir(
        parse_surface_script(dsl),
        graph=graph,
        name="live MatchStep downstream candidate propagation acceptance",
    )
    if len(workflow.steps) != 3 or not isinstance(workflow.steps[1], MatchStep):
        raise RuntimeError("expected Search -> Match -> GetLightcurve workflow")

    run = plan_workflow(workflow, graph)
    search_run, match_run, get_run = run.steps

    expected_search = {
        ("alerce", "lsst", "query_objects"),
        ("alerce", "ztf", "query_objects"),
    }
    actual_search = {
        (plan.broker, plan.origin, plan.endpoint)
        for plan in search_run.endpoint_plans
    }
    if actual_search != expected_search:
        raise RuntimeError(f"unexpected physical search plan: {sorted(actual_search)!r}")
    if match_run.endpoint_plans:
        raise RuntimeError("MatchStep unexpectedly acquired a physical endpoint plan")
    if match_run.candidate_input_from is None or match_run.candidate_input_from.step_index != 0:
        raise RuntimeError("MatchStep does not consume the Search semantic view")

    get_plans = get_run.endpoint_plans
    if len(get_plans) != 1:
        raise RuntimeError(f"expected one downstream Fink plan, found {len(get_plans)}")
    get_plan = get_plans[0]
    if (get_plan.broker, get_plan.origin, get_plan.endpoint) != (
        "fink",
        "ztf",
        "objects",
    ):
        raise RuntimeError(
            "unexpected downstream physical endpoint: "
            f"{get_plan.broker}/{get_plan.origin}/{get_plan.endpoint}"
        )
    if get_plan.candidate_input_from is None or get_plan.candidate_input_from.step_index != 1:
        raise RuntimeError(
            "downstream GetLightcurve is not bound from the MatchStep candidate population"
        )

    print("=== PLAN ===")
    for step_run in run.steps:
        step = run.step_at(step_run.step_index)
        print(
            f"Step {step_run.step_index}: op={step.op} "
            f"candidate_input_from={step_run.candidate_input_from!r}"
        )
        for plan in step_run.endpoint_plans:
            print(
                f"  {plan.broker}/{plan.origin}/{plan.endpoint} "
                f"candidate_input_from={plan.candidate_input_from!r}"
            )
    print("OK: downstream Fink plan depends on MatchStep, not Search")
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

    if staged.run.steps[0].state is not StepRunState.SUCCEEDED:
        raise RuntimeError("Search Step did not succeed")
    if staged.run.steps[1].state is not StepRunState.PLANNED:
        raise RuntimeError("MatchStep must remain planned before final local semantic execution")
    if staged.run.steps[2].state is not StepRunState.SUCCEEDED:
        raise RuntimeError("downstream GetLightcurve Step did not succeed")
    if staged.bindings[1].bound_calls or staged.execution.steps[1].executions:
        raise RuntimeError("MatchStep fabricated physical work")

    search_view = staged.normalized.steps[0]
    search_identities = _identity_set(search_view)
    search_counts = Counter(origin for origin, _ in search_identities)

    finalized = finalize_local_semantics(staged.normalized)
    if finalized.run.steps[1].state is not StepRunState.SUCCEEDED:
        raise RuntimeError("MatchStep did not become succeeded during local semantic execution")
    match_view = finalized.steps[1]
    match_identities = _identity_set(match_view)
    match_counts = Counter(origin for origin, _ in match_identities)

    expected_downstream_ids = {
        object_id for origin, object_id in match_identities if origin == "ztf"
    }
    search_ztf_ids = {
        object_id for origin, object_id in search_identities if origin == "ztf"
    }

    print("=== POPULATIONS ===")
    print(
        f"Search: {len(search_identities)} semantic Portfolios "
        f"{dict(sorted(search_counts.items()))}"
    )
    print(
        f"Match:  {len(match_identities)} semantic Portfolios "
        f"{dict(sorted(match_counts.items()))}"
    )
    print(f"matched ZTF candidates eligible for Fink: {len(expected_downstream_ids)}")
    print()

    if not match_identities:
        if staged.bindings[2].bound_calls:
            raise RuntimeError("empty Match unexpectedly produced a downstream provider call")
        print("INCONCLUSIVE: Match produced no survivors; vacuous downstream behavior was correct")
        return 3
    if not expected_downstream_ids:
        if staged.bindings[2].bound_calls:
            raise RuntimeError("Match has no ZTF survivors but Fink was still called")
        print("INCONCLUSIVE: Match produced survivors, but none are ZTF candidates for Fink")
        return 3

    if len(staged.bindings[2].bound_calls) != 1:
        raise RuntimeError(
            "expected exactly one downstream Fink call for non-empty matched ZTF population"
        )
    bound_call = staged.bindings[2].bound_calls[0]
    actual_downstream_ids = set(_csv_ids(bound_call.params.get("objectId")))

    if actual_downstream_ids != expected_downstream_ids:
        missing = sorted(expected_downstream_ids - actual_downstream_ids)
        leaked = sorted(actual_downstream_ids - expected_downstream_ids)
        raise RuntimeError(
            "downstream candidate propagation mismatch: "
            f"missing matched IDs={missing!r}; leaked non-match IDs={leaked!r}"
        )
    if not actual_downstream_ids.issubset(search_ztf_ids):
        raise RuntimeError("downstream binding contains an ID absent from the Search population")

    unmatched_search_ztf = search_ztf_ids - expected_downstream_ids
    leaked_unmatched = actual_downstream_ids.intersection(unmatched_search_ztf)
    if leaked_unmatched:
        raise RuntimeError(
            f"unmatched Search candidates leaked downstream: {sorted(leaked_unmatched)!r}"
        )

    print("=== DOWNSTREAM BINDING ===")
    print("physical endpoint: fink/ztf/objects")
    print(f"bound objectId count: {len(actual_downstream_ids)}")
    if len(actual_downstream_ids) <= 30:
        for object_id in sorted(actual_downstream_ids):
            print(f"  {object_id}")
    else:
        print("  (ID list suppressed; more than 30 matched ZTF candidates)")
    print(f"unmatched Search ZTF candidates excluded: {len(unmatched_search_ztf)}")

    downstream_view = staged.normalized.steps[2]
    returned_identities = _identity_set(downstream_view)
    returned_ztf_ids = {
        object_id for origin, object_id in returned_identities if origin == "ztf"
    }
    unexpected_returns = returned_ztf_ids - actual_downstream_ids
    if unexpected_returns:
        raise RuntimeError(
            "Fink normalized output contains IDs outside the bound Match population: "
            f"{sorted(unexpected_returns)!r}"
        )
    print(f"Fink returned semantic Portfolios: {len(downstream_view.portfolios)}")

    if args.expect_lsst_id and args.expect_ztf_id:
        expected_lsst = ("lsst", str(args.expect_lsst_id))
        expected_ztf = ("ztf", str(args.expect_ztf_id))
        missing_survivors = [
            identity
            for identity in (expected_lsst, expected_ztf)
            if identity not in match_identities
        ]
        if missing_survivors:
            print(f"FAIL: expected identities did not survive Match: {missing_survivors!r}")
            return 2
        if str(args.expect_ztf_id) not in actual_downstream_ids:
            print("FAIL: expected matched ZTF identity did not propagate to Fink")
            return 2
        print(
            "OK: expected LSST/ZTF identities survived Match and the ZTF identity "
            "propagated to Fink"
        )

    print("OK: Search output remained broader than the Match filter where applicable")
    print("OK: no unmatched Search ZTF identity leaked into downstream binding")
    print("OK: MatchStep created no physical execution")
    print("MATCHSTEP DOWNSTREAM LIVE ACCEPTANCE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
