#!/usr/bin/env python3
"""Live positional MatchStep acceptance through ALeRCE.

The workflow is intentionally literal DSL and keeps discovery, harmonization, and
matching distinct::

    objects from lsst, ztf via alerce
        inside (<ra>, <dec>, <search radius>)
        match on position inside <match radius>

Search owns the two physical ALeRCE endpoint executions; page-based transport is
exhausted by the endpoint executor before normalization. MatchStep is local and runs
only after normalization. Exact ``(origin, object_id)`` duplicates are harmonization
inputs; after that, any distinct semantic identities selected by the explicit Match
operation may receive ``--spatially_near--`` adjacency, whether they share an origin
or not.
"""

from __future__ import annotations

import argparse
from collections import Counter
from itertools import combinations
from math import acos, cos, radians, sin

from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import compile_surface_to_ir, parse_surface_script
from alertissimo.orchestration.ir import MatchStep
from alertissimo.orchestration.local_semantics import finalize_local_semantics
from alertissimo.orchestration.normalization import summary_object_identity
from alertissimo.orchestration.pipeline import execute_staged_workflow_run
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import StepRunState


DEFAULT_RA = 305.5822327501884
DEFAULT_DEC = -18.7909207179724
DEFAULT_SEARCH_RADIUS_ARCSEC = 300.0
DEFAULT_MATCH_RADIUS_ARCSEC = 1.0


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run live ALeRCE LSST+ZTF discovery then local positional MatchStep."
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
        help="Require this LSST object identity to be discovered and matched to --expect-ztf-id.",
    )
    parser.add_argument(
        "--expect-ztf-id",
        help="Require this ZTF object identity to be discovered and matched to --expect-lsst-id.",
    )
    parser.add_argument("--plan-only", action="store_true")
    return parser.parse_args()


def _identity(portfolio):
    identity = summary_object_identity(portfolio)
    return identity if identity is not None else ("unknown", portfolio.internal_portfolio_id.value)


def _summary_position(portfolio):
    positions = []
    for record in portfolio.records:
        if record.semantic_type.split("@", 1)[0] != "summary":
            continue
        ra = record.fields.get("position.ra")
        dec = record.fields.get("position.dec")
        if ra is not None and dec is not None:
            point = (float(ra), float(dec))
            if point not in positions:
                positions.append(point)
    return positions[0] if len(positions) == 1 else None


def _separation_arcsec(left, right):
    ra1, dec1 = map(radians, left)
    ra2, dec2 = map(radians, right)
    cosine = sin(dec1) * sin(dec2) + cos(dec1) * cos(dec2) * cos(ra1 - ra2)
    cosine = max(-1.0, min(1.0, cosine))
    return acos(cosine) * 206264.80624709636


def _nearest_cross_origin_pair(identities):
    positioned = [
        (identity, _summary_position(portfolio))
        for identity, portfolio in identities.items()
    ]
    candidates = []
    for (left_identity, left_position), (right_identity, right_position) in combinations(
        positioned, 2
    ):
        if left_position is None or right_position is None:
            continue
        if left_identity[0] == right_identity[0]:
            continue
        candidates.append(
            (
                _separation_arcsec(left_position, right_position),
                left_identity,
                right_identity,
            )
        )
    return min(candidates, default=None)


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
"""
    print("=== DSL ===")
    print(dsl.rstrip())
    print()

    graph = build_capability_graph()
    workflow = compile_surface_to_ir(
        parse_surface_script(dsl),
        graph=graph,
        name="live LSST-ZTF positional MatchStep acceptance",
    )
    if len(workflow.steps) != 2 or not isinstance(workflow.steps[1], MatchStep):
        raise RuntimeError("expected cone-search followed by one MatchStep")

    run = plan_workflow(workflow, graph)
    search_run, match_run = run.steps
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
        raise RuntimeError("MatchStep does not consume the discovery semantic view")

    print("=== PLAN ===")
    for step_run in run.steps:
        step = run.step_at(step_run.step_index)
        print(
            f"Step {step_run.step_index}: op={step.op} "
            f"candidate_input_from={step_run.candidate_input_from!r}"
        )
        for plan in step_run.endpoint_plans:
            print(f"  {plan.broker}/{plan.origin}/{plan.endpoint}")
    print("OK: MatchStep owns no physical call")
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
        raise RuntimeError("discovery Step did not succeed")
    if staged.run.steps[1].state is not StepRunState.PLANNED:
        raise RuntimeError("MatchStep must remain planned before local semantic execution")
    if staged.bindings[1].bound_calls or staged.execution.steps[1].executions:
        raise RuntimeError("MatchStep fabricated physical work")

    search_view = staged.normalized.steps[0]
    search_identity_items = [(_identity(portfolio), portfolio) for portfolio in search_view.portfolios]
    search_identities = dict(search_identity_items)
    origin_counts = Counter(identity[0] for identity in search_identities)

    print("=== DISCOVERY ===")
    print(f"semantic Portfolios: {len(search_view.portfolios)}")
    print(f"by origin: {dict(sorted(origin_counts.items()))}")
    if not origin_counts.get("lsst") or not origin_counts.get("ztf"):
        print("INCONCLUSIVE: live search did not return candidates from both origins")
        return 3

    nearest = _nearest_cross_origin_pair(search_identities)
    if nearest is not None:
        separation, left, right = nearest
        print(
            "nearest cross-origin summaries: "
            f"{left} <-> {right} = {separation:.6f} arcsec"
        )

    expected_pair = None
    if args.expect_lsst_id and args.expect_ztf_id:
        expected_pair = tuple(
            sorted(
                (
                    ("lsst", str(args.expect_lsst_id)),
                    ("ztf", str(args.expect_ztf_id)),
                )
            )
        )
        missing = [identity for identity in expected_pair if identity not in search_identities]
        for identity in expected_pair:
            portfolio = search_identities.get(identity)
            print(
                f"expected {identity}: "
                + (
                    f"FOUND summary.position={_summary_position(portfolio)!r}"
                    if portfolio is not None
                    else "MISSING"
                )
            )
        if missing:
            print(f"FAIL: expected candidates missing after paginated discovery: {missing!r}")
            return 2
        expected_separation = _separation_arcsec(
            _summary_position(search_identities[expected_pair[0]]),
            _summary_position(search_identities[expected_pair[1]]),
        )
        print(f"expected-pair summary separation: {expected_separation:.6f} arcsec")

    finalized = finalize_local_semantics(staged.normalized)
    if finalized.run.steps[1].state is not StepRunState.SUCCEEDED:
        raise RuntimeError("local MatchStep did not become succeeded")
    if any(portfolio.edges for portfolio in finalized.steps[0].portfolios):
        raise RuntimeError("MatchStep mutated historical Search output")

    match_view = finalized.steps[1]
    semantic = match_view.portfolios
    identity_items = [(_identity(portfolio), portfolio) for portfolio in semantic]
    identities = dict(identity_items)
    if len(identities) != len(identity_items):
        raise RuntimeError(
            "exact (origin, object_id) duplicates survived semantic harmonization before Match"
        )

    print()
    print("=== MATCH VIEW ===")
    print(f"semantic Portfolios: {len(semantic)}")

    edge_ids = set()
    matched_pairs = set()
    pair_separations = {}
    for identity, portfolio in identities.items():
        for edge in portfolio.edges:
            if edge.edge_type != "--spatially_near--":
                continue
            edge_ids.add(edge.internal_edge_id)
            remote = next(
                (
                    other_identity
                    for other_identity, other in identities.items()
                    if other.internal_portfolio_id == edge.target
                ),
                None,
            )
            if remote is None:
                raise RuntimeError("Match edge target is not a semantic Portfolio in the Match view")
            if identity == remote:
                raise RuntimeError("MatchStep produced a self-relation after identity harmonization")
            pair = tuple(sorted((identity, remote)))
            matched_pairs.add(pair)
            pair_separations[pair] = edge.fields.get("angular_separation")

    # Redundant projection means every scientific relation appears in both incident
    # Portfolios but carries one shared InternalEdgeId.
    if len(edge_ids) != len(matched_pairs):
        raise RuntimeError(
            "redundant Portfolio-edge projections do not collapse to one shared ID per match"
        )

    same_origin_pairs = {
        pair for pair in matched_pairs if pair[0][0] == pair[1][0]
    }
    cross_origin_pairs = matched_pairs - same_origin_pairs

    for left, right in sorted(matched_pairs):
        separation = pair_separations[(left, right)]
        suffix = f" ({float(separation):.6f} arcsec)" if separation is not None else ""
        print(f"  {left} <-> {right}{suffix}")
    print(f"unique positional relationships: {len(matched_pairs)}")
    print(f"same-origin distinct-ID relationships: {len(same_origin_pairs)}")
    print(f"cross-origin relationships: {len(cross_origin_pairs)}")
    print("OK: exact same identities were harmonized before Match")
    print("OK: MatchStep created no physical execution provenance")
    print("OK: Search output remained unchanged")

    if expected_pair is not None:
        if expected_pair not in matched_pairs:
            print(f"FAIL: expected positional relationship was not produced: {expected_pair!r}")
            return 2
        print(
            "OK: expected LSST/ZTF pair matched at "
            f"{float(pair_separations[expected_pair]):.6f} arcsec"
        )

    if not matched_pairs:
        print(
            "INCONCLUSIVE: selected candidates were normalized correctly, but none are inside "
            f"{args.match_radius_arcsec} arcsec"
        )
        return 3

    print("MATCHSTEP LIVE ACCEPTANCE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
