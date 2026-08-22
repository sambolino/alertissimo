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

ALeRCE performs live LSST+ZTF discovery. MatchStep executes locally over normalized
semantic positions. The downstream GetLightcurve is then realized by the registered
Fink capabilities for both origins: LSST sources plus its optional forced-photometry
supplement, and ZTF objects. Every physical plan must receive only Match survivors
from its own origin.
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

EXPECTED_FINK_PLANS = {
    ("fink", "lsst", "sources"): ("lsst", "diaObjectId", True),
    ("fink", "lsst", "fp"): ("lsst", "diaObjectId", False),
    ("fink", "ztf", "objects"): ("ztf", "objectId", True),
}


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run live ALeRCE LSST+ZTF discovery, local positional MatchStep, then "
            "verify that Fink lightcurve retrieval receives only matched IDs."
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
        help="Require this LSST identity to survive Match and propagate to Fink/LSST.",
    )
    parser.add_argument(
        "--expect-ztf-id",
        help="Require this ZTF identity to survive Match and propagate to Fink/ZTF.",
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


def _ids_by_origin(identities: set[tuple[str, str]]) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = {}
    for origin, object_id in identities:
        grouped.setdefault(origin, set()).add(object_id)
    return grouped


def _csv_ids(value, *, physical_name: str) -> tuple[str, ...]:
    if not isinstance(value, str):
        raise RuntimeError(
            f"Fink binding {physical_name!r} did not materialize as a CSV string: {value!r}"
        )
    values = tuple(item.strip() for item in value.split(",") if item.strip())
    if len(values) != len(set(values)):
        raise RuntimeError(
            f"downstream {physical_name} binding contains duplicates: {values!r}"
        )
    return values


def _plan_key(plan) -> tuple[str, str, str]:
    return plan.broker, plan.origin, plan.endpoint


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
    actual_search = {_plan_key(plan) for plan in search_run.endpoint_plans}
    if actual_search != expected_search:
        raise RuntimeError(f"unexpected physical search plan: {sorted(actual_search)!r}")
    if match_run.endpoint_plans:
        raise RuntimeError("MatchStep unexpectedly acquired a physical endpoint plan")
    if match_run.candidate_input_from is None or match_run.candidate_input_from.step_index != 0:
        raise RuntimeError("MatchStep does not consume the Search semantic view")

    get_plans = {_plan_key(plan): plan for plan in get_run.endpoint_plans}
    if set(get_plans) != set(EXPECTED_FINK_PLANS):
        raise RuntimeError(
            "unexpected downstream Fink plan set: "
            f"{sorted(get_plans)!r}; expected {sorted(EXPECTED_FINK_PLANS)!r}"
        )
    for key, plan in get_plans.items():
        _, _, expected_required = EXPECTED_FINK_PLANS[key]
        if plan.required is not expected_required:
            raise RuntimeError(
                f"downstream plan {key!r} required={plan.required!r}; "
                f"expected {expected_required!r}"
            )
        if plan.candidate_input_from is None or plan.candidate_input_from.step_index != 1:
            raise RuntimeError(
                f"downstream plan {key!r} is not bound from the MatchStep population"
            )

    print("=== PLAN ===")
    for step_run in run.steps:
        step = run.step_at(step_run.step_index)
        print(
            f"Step {step_run.step_index}: op={step.op} "
            f"candidate_input_from={step_run.candidate_input_from!r}"
        )
        for plan in step_run.endpoint_plans:
            requirement = "required" if plan.required else "supplementary"
            print(
                f"  {plan.broker}/{plan.origin}/{plan.endpoint} "
                f"candidate_input_from={plan.candidate_input_from!r} {requirement}"
            )
    print("OK: every downstream Fink plan depends on MatchStep, not Search")
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
    search_by_origin = _ids_by_origin(search_identities)

    finalized = finalize_local_semantics(staged.normalized)
    if finalized.run.steps[1].state is not StepRunState.SUCCEEDED:
        raise RuntimeError("MatchStep did not become succeeded during local semantic execution")
    match_view = finalized.steps[1]
    match_identities = _identity_set(match_view)
    match_counts = Counter(origin for origin, _ in match_identities)
    match_by_origin = _ids_by_origin(match_identities)

    print("=== POPULATIONS ===")
    print(
        f"Search: {len(search_identities)} semantic Portfolios "
        f"{dict(sorted(search_counts.items()))}"
    )
    print(
        f"Match:  {len(match_identities)} semantic Portfolios "
        f"{dict(sorted(match_counts.items()))}"
    )
    print()

    if not match_identities:
        if staged.bindings[2].bound_calls:
            raise RuntimeError("empty Match unexpectedly produced downstream provider calls")
        print("INCONCLUSIVE: Match produced no survivors; vacuous downstream behavior was correct")
        return 3

    calls_by_key = {
        _plan_key(call.endpoint_plan): call for call in staged.bindings[2].bound_calls
    }
    if len(calls_by_key) != len(staged.bindings[2].bound_calls):
        raise RuntimeError("duplicate downstream Fink physical calls share one endpoint identity")

    actual_bound_by_origin: dict[str, set[str]] = {"lsst": set(), "ztf": set()}
    print("=== DOWNSTREAM BINDINGS ===")
    for key in sorted(EXPECTED_FINK_PLANS):
        origin, physical_name, required = EXPECTED_FINK_PLANS[key]
        expected_ids = match_by_origin.get(origin, set())
        call = calls_by_key.get(key)

        if not expected_ids:
            if call is not None:
                raise RuntimeError(
                    f"{key!r} was called even though Match has no {origin!r} survivors"
                )
            print(f"{key[0]}/{key[1]}/{key[2]}: vacuous (0 matched {origin} IDs)")
            continue

        if call is None:
            raise RuntimeError(
                f"{key!r} has {len(expected_ids)} matched {origin} candidates but no bound call"
            )
        actual_ids = set(
            _csv_ids(call.params.get(physical_name), physical_name=physical_name)
        )
        if actual_ids != expected_ids:
            missing = sorted(expected_ids - actual_ids)
            leaked = sorted(actual_ids - expected_ids)
            raise RuntimeError(
                f"downstream propagation mismatch for {key!r}: "
                f"missing matched IDs={missing!r}; leaked non-match IDs={leaked!r}"
            )

        search_ids = search_by_origin.get(origin, set())
        if not actual_ids.issubset(search_ids):
            raise RuntimeError(
                f"{key!r} binding contains an ID absent from the {origin} Search population"
            )
        unmatched_search_ids = search_ids - expected_ids
        leaked_unmatched = actual_ids.intersection(unmatched_search_ids)
        if leaked_unmatched:
            raise RuntimeError(
                f"unmatched {origin} Search candidates leaked into {key!r}: "
                f"{sorted(leaked_unmatched)!r}"
            )

        actual_bound_by_origin.setdefault(origin, set()).update(actual_ids)
        requirement = "required" if required else "supplementary"
        print(
            f"{key[0]}/{key[1]}/{key[2]}: {len(actual_ids)} IDs, {requirement}; "
            f"excluded {len(unmatched_search_ids)} unmatched {origin} Search IDs"
        )
        if len(actual_ids) <= 20:
            for object_id in sorted(actual_ids):
                print(f"  {object_id}")

    downstream_view = staged.normalized.steps[2]
    returned_identities = _identity_set(downstream_view)
    unexpected_returns = returned_identities - match_identities
    if unexpected_returns:
        raise RuntimeError(
            "Fink normalized output contains identities outside the Match population: "
            f"{sorted(unexpected_returns)!r}"
        )
    print(f"Fink returned semantic Portfolios: {len(downstream_view.portfolios)}")
    if staged.run.steps[2].warnings:
        print("supplementary warnings:")
        for warning in staged.run.steps[2].warnings:
            print(f"  {warning}")

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
        if str(args.expect_lsst_id) not in actual_bound_by_origin.get("lsst", set()):
            print("FAIL: expected matched LSST identity did not propagate to Fink/LSST")
            return 2
        if str(args.expect_ztf_id) not in actual_bound_by_origin.get("ztf", set()):
            print("FAIL: expected matched ZTF identity did not propagate to Fink/ZTF")
            return 2
        print("OK: expected LSST/ZTF identities both propagated through Match to Fink")

    for origin in ("lsst", "ztf"):
        expected_ids = match_by_origin.get(origin, set())
        if expected_ids and actual_bound_by_origin.get(origin, set()) != expected_ids:
            raise RuntimeError(
                f"not every matched {origin} identity reached a downstream Fink plan"
            )

    print("OK: Search output remained unchanged and broader than Match where applicable")
    print("OK: no unmatched Search identity leaked into downstream Fink bindings")
    print("OK: MatchStep created no physical execution")
    print("MATCHSTEP DOWNSTREAM LIVE ACCEPTANCE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
