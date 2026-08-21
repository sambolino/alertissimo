#!/usr/bin/env python3
"""Live multi-survey DSL acceptance / diagnostic harness.

Purpose
-------
Exercise one semantic workflow spanning more than one survey namespace and verify
that runtime-discovered candidate identities remain origin-aware.

The current architecture risk this script is designed to expose is:

    LSST candidates + ZTF candidates
              |
              v
      flattened object-id tuple
              |
              +--> Fink/LSST target binding   (WRONG if ZTF IDs are included)
              |
              +--> Fink/ZTF target binding    (WRONG if LSST IDs are included)

The correct future behavior is:

    LSST candidates ---> only LSST downstream plans
    ZTF candidates  ---> only ZTF downstream plans

The DSL and WorkflowIR remain survey/provider-neutral; this is a runtime routing
property.

By default a routing guard rejects an obviously cross-survey target list BEFORE it
is sent to the provider. Once origin-aware candidate routing is implemented, the
guard becomes silent and the script proceeds through normalization and invariants.

Typical use:

    PYTHONPATH=. python scripts/live_dsl_multisurvey.py

If the default sky position does not currently return candidates from both surveys,
try a larger cone or a known overlap field:

    PYTHONPATH=. python scripts/live_dsl_multisurvey.py --radius-arcsec 900

To inspect lowering/planning only:

    PYTHONPATH=. python scripts/live_dsl_multisurvey.py --plan-only

To disable the safety guard and let the actual runtime bindings reach providers:

    PYTHONPATH=. python scripts/live_dsl_multisurvey.py --no-routing-guard

The default position is the already-used live ZTF cone from the Alertissimo smoke
suite. It is intentionally configurable because live LSST broker holdings evolve.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import compile_surface_to_ir, parse_surface_script
from alertissimo.orchestration.normalization import normalize_execution
from alertissimo.orchestration.pipeline import execute_staged_workflow_run
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import WorkflowExecutionError


DEFAULT_RA = 124.87996115142856
DEFAULT_DEC = -6.0205001
DEFAULT_RADIUS_ARCSEC = 300.0


class RoutingGuardError(RuntimeError):
    """A target-bound live call contains IDs from an incompatible survey namespace."""


@dataclass(frozen=True)
class ObservedCall:
    broker: str
    origin: str
    endpoint: str
    params: dict[str, Any]


def _csv_items(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (tuple, list)):
        return tuple(str(item) for item in value)
    if isinstance(value, str):
        return tuple(item for item in value.split(",") if item)
    return (str(value),)


def _looks_compatible_with_origin(origin: str, object_id: str) -> bool:
    """Diagnostic namespace heuristic, deliberately kept out of Alertissimo core.

    This is only a safety guard for this live script:
      - ZTF object IDs are names such as ZTF20acpwljl.
      - Rubin/LSST diaObjectIds used by the current providers are decimal IDs.

    The actual architecture fix must route by semantic origin/namespace evidence,
    not by inspecting identifier spelling.
    """

    if origin == "ztf":
        return object_id.startswith("ZTF")
    if origin == "lsst":
        return object_id.isdigit()
    return True


class GuardedExecutor:
    """Trace live calls and block obviously cross-survey target bindings."""

    def __init__(
        self,
        registry: EndpointRegistry,
        *,
        routing_guard: bool = True,
    ) -> None:
        self.registry = registry
        self.routing_guard = routing_guard
        self.delegate = RegistryEndpointExecutor(registry=registry)
        self.calls: list[ObservedCall] = []

    def _target_values(
        self,
        broker: str,
        origin: str,
        endpoint: str,
        params: dict[str, Any],
    ) -> tuple[str, ...]:
        spec = self.registry.resolve(broker, origin, endpoint)
        values: list[str] = []
        for physical_name, declaration in spec.params.items():
            declaration = declaration or {}
            if declaration.get("bind") != "target_id":
                continue
            if physical_name not in params:
                continue
            values.extend(_csv_items(params[physical_name]))
        return tuple(values)

    def execute(
        self,
        broker: str,
        origin: str,
        endpoint: str,
        params=None,
        headers=None,
    ):
        supplied = dict(params or {})
        self.calls.append(ObservedCall(broker, origin, endpoint, supplied))

        target_values = self._target_values(
            broker, origin, endpoint, supplied
        )
        incompatible = tuple(
            value
            for value in target_values
            if not _looks_compatible_with_origin(origin, value)
        )
        if self.routing_guard and incompatible:
            raise RoutingGuardError(
                "origin-aware candidate routing violation before provider call: "
                f"{broker}/{origin}/{endpoint} would receive incompatible target ID(s) "
                f"{list(incompatible)!r}; full target set={list(target_values)!r}. "
                "The diagnostic guard blocked this call before network execution."
            )

        return self.delegate.execute(
            broker=broker,
            origin=origin,
            endpoint=endpoint,
            params=supplied,
            headers=headers,
        )


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


def _find_step_result(results: Iterable[Any], step_index: int):
    return next(
        (result for result in results if result.step_index == step_index),
        None,
    )


def _bound_target_ids(call, registry: EndpointRegistry) -> tuple[str, ...]:
    plan = call.endpoint_plan
    spec = registry.resolve(plan.broker, plan.origin, plan.endpoint)
    values: list[str] = []
    for physical_name, declaration in spec.params.items():
        declaration = declaration or {}
        if declaration.get("bind") != "target_id":
            continue
        if physical_name in call.params:
            values.extend(_csv_items(call.params[physical_name]))
    return tuple(values)


def _print_workflow(workflow) -> None:
    print("=== LOWERED SEMANTIC WORKFLOW ===")
    for index, step in enumerate(workflow.steps):
        sources = [(source.broker, source.origin) for source in step.sources]
        target = getattr(step, "target", None)
        print(
            f"Step {index}: op={step.op} "
            f"target={target.model_dump() if target is not None else None} "
            f"sources={sources}"
        )
    print()


def _print_plan(run) -> None:
    print("=== PHYSICAL PLAN ===")
    for step_run in run.steps:
        print(f"Semantic Step {step_run.step_index}:")
        if not step_run.endpoint_plans:
            print("  (no provider endpoint)")
            continue
        for plan_index, plan in enumerate(step_run.endpoint_plans):
            print(
                f"  plan {plan_index}: "
                f"{plan.broker}/{plan.origin}/{plan.endpoint}"
            )
            print(f"    execution_reuse_from={plan.execution_reuse_from}")
            print(f"    candidate_input_from={plan.candidate_input_from}")
            realization = plan.predicate_realization
            if realization is not None:
                print(f"    pushdown={realization.pushdown}")
                print(f"    residual={realization.residual}")
                print(f"    params={dict(realization.params)}")
    print()


def _print_observed_calls(calls: Iterable[ObservedCall]) -> None:
    print("=== OBSERVED PHYSICAL CALLS ===")
    calls = tuple(calls)
    if not calls:
        print("(none)")
    for index, call in enumerate(calls):
        print(
            f"{index}: {call.broker}/{call.origin}/{call.endpoint} "
            f"params={call.params}"
        )
    print()


def _print_candidates(grouped: dict[str, tuple[str, ...]]) -> None:
    print("=== NORMALIZED SEARCH CANDIDATES BY ORIGIN ===")
    if not grouped:
        print("(no normalized candidate identities recovered)")
    for origin in sorted(grouped):
        print(
            f"{origin}: {len(grouped[origin])} candidate(s) "
            f"{list(grouped[origin])}"
        )
    print()


def _print_normalized(staged) -> None:
    print("=== NORMALIZED OUTPUT ===")
    for step in staged.normalized.steps:
        execution_ids = [execution.execution_id for execution in step.executions]
        portfolio_count = sum(
            len(execution.portfolios) for execution in step.executions
        )
        ids = _summary_object_ids(
            portfolio
            for execution in step.executions
            for portfolio in execution.portfolios
        )
        print(
            f"Semantic Step {step.step_index}: "
            f"executions={execution_ids} "
            f"portfolios={portfolio_count} "
            f"object_ids={list(ids)}"
        )
    print()


def _assert_origin_routing(
    staged,
    registry: EndpointRegistry,
    candidate_ids_by_origin: dict[str, tuple[str, ...]],
) -> None:
    expected = {
        origin: set(values)
        for origin, values in candidate_ids_by_origin.items()
    }

    checked = 0
    errors: list[str] = []

    # Step 0 is candidate discovery. Every later target-bound call must receive only
    # candidates belonging to its own endpoint origin.
    for binding in staged.bindings[1:]:
        for call in binding.bound_calls:
            target_ids = _bound_target_ids(call, registry)
            if not target_ids:
                continue
            checked += 1
            plan = call.endpoint_plan
            allowed = expected.get(plan.origin, set())
            received = set(target_ids)
            wrong = received - allowed
            if wrong:
                errors.append(
                    f"{plan.broker}/{plan.origin}/{plan.endpoint}: "
                    f"received {sorted(received)!r}, but normalized "
                    f"{plan.origin!r} candidates are {sorted(allowed)!r}; "
                    f"foreign IDs={sorted(wrong)!r}"
                )

    if errors:
        raise RuntimeError(
            "origin-aware downstream routing invariant failed:\n  - "
            + "\n  - ".join(errors)
        )
    if checked == 0:
        raise RuntimeError(
            "no downstream target-bound call was observed; "
            "multi-survey routing was not exercised"
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a live Fink LSST+ZTF DSL workflow and diagnose "
            "origin-aware candidate routing."
        )
    )
    parser.add_argument("--ra", type=float, default=DEFAULT_RA)
    parser.add_argument("--dec", type=float, default=DEFAULT_DEC)
    parser.add_argument(
        "--radius-arcsec",
        type=float,
        default=DEFAULT_RADIUS_ARCSEC,
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="compile and plan only; do not contact providers",
    )
    parser.add_argument(
        "--no-routing-guard",
        action="store_true",
        help=(
            "disable the diagnostic namespace guard and allow runtime-bound "
            "target lists to reach providers"
        ),
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

    dsl = f"""objects from lsst, ztf via fink
    inside ({args.ra}, {args.dec}, {args.radius_arcsec}arcsec)
    with lightcurve via fink
"""

    print("=== DSL ===")
    print(dsl.rstrip())
    print()

    graph = build_capability_graph()
    surface = parse_surface_script(dsl)
    workflow = compile_surface_to_ir(
        surface,
        graph=graph,
        name="live multi-survey candidate routing",
    )
    _print_workflow(workflow)

    run = plan_workflow(workflow, graph)
    _print_plan(run)

    # We expect exactly one semantic candidate-discovery Step followed by one
    # semantic lightcurve requirement. The lightcurve Step may own several physical
    # plans (e.g. LSST sources + LSST fp + ZTF objects).
    print("=== PRE-LIVE INVARIANTS ===")
    if len(workflow.steps) != 2:
        raise RuntimeError(
            f"expected 2 semantic Steps, got {len(workflow.steps)}"
        )
    if workflow.steps[0].op not in {"cone_search", "semantic_search"}:
        raise RuntimeError(
            f"expected candidate search at Step 0, got {workflow.steps[0].op}"
        )
    if workflow.steps[1].op != "get_lightcurve":
        raise RuntimeError(
            f"expected get_lightcurve at Step 1, got {workflow.steps[1].op}"
        )
    search_origins = {plan.origin for plan in run.steps[0].endpoint_plans}
    lightcurve_origins = {plan.origin for plan in run.steps[1].endpoint_plans}
    print(f"OK: search origins={sorted(search_origins)}")
    print(f"OK: lightcurve plan origins={sorted(lightcurve_origins)}")
    print(
        "OK: WorkflowIR lightcurve target remains "
        f"{getattr(workflow.steps[1], 'target', None)}"
    )
    print()

    if args.plan_only:
        print("Plan-only mode: no provider APIs contacted.")
        return 0

    registry = EndpointRegistry()
    executor = GuardedExecutor(
        registry,
        routing_guard=not args.no_routing_guard,
    )

    try:
        staged = execute_staged_workflow_run(
            run,
            registry,
            executor,
        )
    except WorkflowExecutionError as error:
        _print_observed_calls(executor.calls)

        search_result = _find_step_result(error.completed_steps, 0)
        grouped: dict[str, tuple[str, ...]] = {}
        if search_result is not None:
            grouped = _candidate_ids_by_origin(search_result)
        _print_candidates(grouped)

        print("=== STAGED EXECUTION FAILED ===")
        print(str(error))
        failed = next(
            (
                step
                for step in error.workflow_run.steps
                if step.state.value == "failed"
            ),
            None,
        )
        if failed is not None:
            print(f"failed step: {failed.step_index}")
            print(f"runtime error: {failed.error}")
        print()

        diagnostic = (
            "RoutingGuardError" in str(error)
            or (failed is not None and "RoutingGuardError" in (failed.error or ""))
        )
        if diagnostic:
            print("=== DIAGNOSIS ===")
            print(
                "The current staged runtime attempted to feed candidate IDs from "
                "one survey namespace into a downstream endpoint for another "
                "survey. The guard blocked the invalid provider call."
            )
            print(
                "This is the expected acceptance failure until candidate identity "
                "is propagated as (origin, object_id) rather than a globally "
                "flattened object-id tuple."
            )
            if set(grouped) != {"lsst", "ztf"}:
                print(
                    "NOTE: candidates were not recovered from both origins, so "
                    "this run may not fully exercise the intended LSST+ZTF case."
                )
            return 2
        raise

    _print_observed_calls(executor.calls)

    search_result = _find_step_result(staged.execution.steps, 0)
    if search_result is None:
        raise RuntimeError("completed staged workflow has no Step 0 search result")
    grouped = _candidate_ids_by_origin(search_result)
    _print_candidates(grouped)
    _print_normalized(staged)

    print("=== INVARIANTS ===")
    if set(grouped) != {"lsst", "ztf"}:
        print(
            "INCONCLUSIVE: this live cone did not yield normalized candidates "
            "from both LSST and ZTF."
        )
        print(
            "Try a different overlap field or increase --radius-arcsec, then rerun."
        )
        return 3

    _assert_origin_routing(staged, registry, grouped)
    print("OK: LSST downstream plans received only LSST candidate IDs")
    print("OK: ZTF downstream plans received only ZTF candidate IDs")
    print("OK: candidate routing preserved survey/origin namespaces")
    print(
        "OK: one semantic get_lightcurve Step may still use multiple physical "
        "plans without leaking IDs across origins"
    )
    print()
    print("MULTI-SURVEY ACCEPTANCE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
