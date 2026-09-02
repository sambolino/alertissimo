#!/usr/bin/env python3
"""Live acceptance matrix for cumulative semantic Portfolio material.

This script deliberately rotates ZTF brokers through different orchestration roles
instead of validating one fixed provider chain.  Every row is an independent DSL
workflow over the same tiny sky region::

    discovery broker -> targetless enrichment broker -> targetless enrichment broker

The acceptance contract is architectural rather than provider-content-specific:

* the SearchStep owns the candidate population;
* every downstream physical endpoint binds only those candidate identities;
* every targetless GetStep extends the immediately preceding semantic material view;
* ``StepPortfolioResult.executions`` remains occurrence-local physical work;
* ``StepPortfolioResult.portfolios`` is an immutable cumulative semantic snapshot;
* no later provider execution mutates an earlier Step view.

Provider outages, authentication failures, and a live cone that no longer yields the
expected reference object are reported separately from architecture failures.

Run from the repository root::

    PYTHONPATH=. python scripts/live_dsl_material_lineage.py

Useful options::

    PYTHONPATH=. python scripts/live_dsl_material_lineage.py --list
    PYTHONPATH=. python scripts/live_dsl_material_lineage.py --plan-only
    PYTHONPATH=. python scripts/live_dsl_material_lineage.py --scenario fink-search-alerce-antares
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import os
import re
from typing import Literal

from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import compile_surface_to_ir, parse_surface_script
from alertissimo.orchestration.normalization import summary_object_identity
from alertissimo.orchestration.pipeline import execute_staged_workflow_run
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import (
    CandidateInputRef,
    MaterialInputRef,
    PlanCandidateInputRef,
    StepRunState,
)


Status = Literal["PASS", "INCONCLUSIVE", "UNAVAILABLE", "SKIP", "FAIL"]

DEFAULT_RA = 124.87996115142856
DEFAULT_DEC = -6.0205001
DEFAULT_RADIUS_ARCSEC = 1.0
DEFAULT_EXPECTED_OBJECT_ID = "ZTF20acpwljl"


@dataclass(frozen=True)
class MatrixScenario:
    name: str
    description: str
    discovery_broker: str
    enrichments: tuple[tuple[str, str], ...]
    expected_endpoints: tuple[tuple[tuple[str, str, str], ...], ...]
    required_env: tuple[str, ...] = ()


SCENARIOS: tuple[MatrixScenario, ...] = (
    MatrixScenario(
        name="lasair-search-fink-antares",
        description="Lasair discovery -> Fink lightcurve -> ANTARES crossmatch",
        discovery_broker="lasair",
        enrichments=(("lightcurve", "fink"), ("crossmatch", "antares")),
        expected_endpoints=(
            (("lasair", "ztf", "cone"), ("lasair", "ztf", "query")),
            (("fink", "ztf", "objects"),),
            (("antares", "ztf", "get_by_ztf_object_id"),),
        ),
        required_env=("LASAIR_ZTF_TOKEN",),
    ),
    MatrixScenario(
        name="alerce-search-fink-lasair",
        description="ALeRCE discovery -> Fink lightcurve -> Lasair lightcurve",
        discovery_broker="alerce",
        enrichments=(("lightcurve", "fink"), ("lightcurve", "lasair")),
        expected_endpoints=(
            (("alerce", "ztf", "query_objects"),),
            (("fink", "ztf", "objects"),),
            (("lasair", "ztf", "lightcurves"),),
        ),
        required_env=("LASAIR_ZTF_TOKEN",),
    ),
    MatrixScenario(
        name="fink-search-alerce-antares",
        description="Fink discovery -> ALeRCE lightcurve -> ANTARES crossmatch",
        discovery_broker="fink",
        enrichments=(("lightcurve", "alerce"), ("crossmatch", "antares")),
        expected_endpoints=(
            (("fink", "ztf", "conesearch"),),
            (("alerce", "ztf", "query_lightcurve"),),
            (("antares", "ztf", "get_by_ztf_object_id"),),
        ),
    ),
    MatrixScenario(
        name="antares-search-fink-alerce",
        description="ANTARES discovery -> Fink lightcurve -> ALeRCE lightcurve",
        discovery_broker="antares",
        enrichments=(("lightcurve", "fink"), ("lightcurve", "alerce")),
        expected_endpoints=(
            (("antares", "ztf", "cone_search"),),
            (("fink", "ztf", "objects"),),
            (("alerce", "ztf", "query_lightcurve"),),
        ),
    ),
)


@dataclass(frozen=True)
class ScenarioOutcome:
    scenario: MatrixScenario
    status: Status
    detail: str


_TRANSIENT_PATTERNS = (
    re.compile(r"HTTP Error (?:408|429|5\d\d)\b", re.IGNORECASE),
    re.compile(r"\b(?:502|503|504)\b.*(?:gateway|service|timeout|time-out)", re.IGNORECASE),
    re.compile(r"gateway (?:timeout|time-out)", re.IGNORECASE),
    re.compile(r"service unavailable", re.IGNORECASE),
    re.compile(r"timed?\s*out|timeout(?:error)?", re.IGNORECASE),
    re.compile(r"connection (?:reset|refused|aborted|closed)", re.IGNORECASE),
    re.compile(r"remote end closed connection", re.IGNORECASE),
    re.compile(r"temporary failure in name resolution|name or service not known", re.IGNORECASE),
    re.compile(r"network is unreachable", re.IGNORECASE),
    re.compile(r"urlerror", re.IGNORECASE),
)

_AUTH_PATTERNS = (
    re.compile(r"HTTP Error (?:401|403)\b", re.IGNORECASE),
    re.compile(r"\b(?:401|403)\b.*(?:unauthori[sz]ed|forbidden)", re.IGNORECASE),
    re.compile(r"unauthori[sz]ed|forbidden", re.IGNORECASE),
    re.compile(r"credential.*(?:missing|not found|required)", re.IGNORECASE),
)


def build_dsl(
    scenario: MatrixScenario,
    *,
    ra: float = DEFAULT_RA,
    dec: float = DEFAULT_DEC,
    radius_arcsec: float = DEFAULT_RADIUS_ARCSEC,
) -> str:
    lines = [
        f"objects from ztf via {scenario.discovery_broker}",
        f"inside ({ra}, {dec}, {radius_arcsec}arcsec)",
        "latest 1",
    ]
    lines.extend(
        f"with {product} via {broker}"
        for product, broker in scenario.enrichments
    )
    return "\n".join(lines) + "\n"


def compile_and_plan(
    scenario: MatrixScenario,
    *,
    ra: float = DEFAULT_RA,
    dec: float = DEFAULT_DEC,
    radius_arcsec: float = DEFAULT_RADIUS_ARCSEC,
):
    graph = build_capability_graph()
    dsl = build_dsl(
        scenario,
        ra=ra,
        dec=dec,
        radius_arcsec=radius_arcsec,
    )
    workflow = compile_surface_to_ir(
        parse_surface_script(dsl),
        graph=graph,
        name=f"live material lineage: {scenario.name}",
    )
    run = plan_workflow(workflow, graph)
    return dsl, workflow, run


def assert_plan_contract(scenario: MatrixScenario, workflow, run) -> None:
    expected_step_count = len(scenario.expected_endpoints)
    if len(workflow.steps) != expected_step_count or len(run.steps) != expected_step_count:
        raise RuntimeError(
            f"expected {expected_step_count} semantic Steps, got "
            f"workflow={len(workflow.steps)} run={len(run.steps)}"
        )

    for index, expected in enumerate(scenario.expected_endpoints):
        step_run = run.steps[index]
        actual = tuple(
            (plan.broker, plan.origin, plan.endpoint)
            for plan in step_run.endpoint_plans
        )
        if actual != expected:
            raise RuntimeError(
                f"Step {index} physical plan mismatch: expected {expected!r}, got {actual!r}"
            )

        if index == 0:
            primary = step_run.endpoint_plans[0]
            if primary.candidate_input_from is not None:
                raise RuntimeError("Search primary plan unexpectedly has candidate input")
            for plan_index, plan in enumerate(step_run.endpoint_plans[1:], start=1):
                if plan.candidate_input_from_plan != PlanCandidateInputRef(plan_index=0):
                    raise RuntimeError(
                        f"Search supplementary plan {plan_index} must bind from plan 0; "
                        f"got {plan.candidate_input_from_plan!r}"
                    )
            if step_run.candidate_input_from is not None:
                raise RuntimeError("Search StepRun unexpectedly has candidate input")
            if step_run.material_input_from is not None:
                raise RuntimeError("Search StepRun unexpectedly has material input")
            continue

        plan = step_run.endpoint_plans[0]
        if getattr(workflow.steps[index], "target", None) is not None:
            raise RuntimeError(f"Step {index} leaked a runtime target into WorkflowIR")
        if plan.candidate_input_from != CandidateInputRef(step_index=0):
            raise RuntimeError(
                f"Step {index} physical plan must bind from Search candidates; "
                f"got {plan.candidate_input_from!r}"
            )
        if step_run.candidate_input_from is not None:
            raise RuntimeError(
                f"provider Step {index} must not overload StepRun.candidate_input_from"
            )
        expected_material = MaterialInputRef(step_index=index - 1)
        if step_run.material_input_from != expected_material:
            raise RuntimeError(
                f"Step {index} must enrich material from Step {index - 1}; "
                f"got {step_run.material_input_from!r}"
            )


def _identity_map(step_output) -> dict[tuple[str, str], object]:
    result: dict[tuple[str, str], object] = {}
    for portfolio in step_output.portfolios:
        identity = summary_object_identity(portfolio)
        if identity is None:
            raise RuntimeError(
                f"Step {step_output.step_index} contains a semantic Portfolio without "
                "one unambiguous summary identity"
            )
        normalized = (str(identity[0]), str(identity[1]))
        if normalized in result:
            raise RuntimeError(
                f"Step {step_output.step_index} contains duplicate semantic identity "
                f"{normalized!r} after consolidation"
            )
        result[normalized] = portfolio
    if len(result) != len(step_output.portfolios):
        raise RuntimeError(
            f"Step {step_output.step_index} identity count does not match Portfolio count"
        )
    return result


def _portfolio_execution_ids(portfolio) -> set[str]:
    return {
        execution.internal_execution_id.value
        for execution in portfolio.executions
    }


def _own_execution_ids_by_identity(step_output) -> dict[tuple[str, str], set[str]]:
    result: dict[tuple[str, str], set[str]] = {}
    for execution_group in step_output.executions:
        for portfolio in execution_group.portfolios:
            identity = summary_object_identity(portfolio)
            if identity is None:
                raise RuntimeError(
                    f"Step {step_output.step_index} own physical output contains a "
                    "Portfolio without one unambiguous summary identity"
                )
            normalized = (str(identity[0]), str(identity[1]))
            result.setdefault(normalized, set()).update(_portfolio_execution_ids(portfolio))
    return result


def _semantic_types(step_output) -> Counter[str]:
    return Counter(
        record.semantic_type
        for portfolio in step_output.portfolios
        for record in portfolio.records
    )


def assert_live_material_contract(staged, *, expected_object_id: str | None) -> tuple[bool, str]:
    normalized = staged.normalized
    search_map = _identity_map(normalized.steps[0])
    if not search_map:
        return False, "live discovery returned no semantic Portfolios"

    search_ids = set(search_map)
    expected_identity = (
        ("ztf", str(expected_object_id)) if expected_object_id is not None else None
    )
    expected_found = expected_identity is None or expected_identity in search_ids

    cumulative_execution_ids: dict[tuple[str, str], set[str]] = {
        identity: set() for identity in search_ids
    }

    all_runtime_execution_ids: set[str] = set()
    for step_index, (step_run, step_output) in enumerate(
        zip(staged.run.steps, normalized.steps)
    ):
        if step_run.state is not StepRunState.SUCCEEDED:
            raise RuntimeError(
                f"Step {step_index} state is {step_run.state.value!r}, expected succeeded"
            )

        runtime_ids = set(step_run.execution_ids)
        output_group_ids = {execution.execution_id for execution in step_output.executions}
        if runtime_ids != output_group_ids:
            raise RuntimeError(
                f"Step {step_index} physical ownership mismatch: runtime={sorted(runtime_ids)!r}, "
                f"normalized execution groups={sorted(output_group_ids)!r}"
            )
        if all_runtime_execution_ids.intersection(runtime_ids):
            raise RuntimeError(
                f"Step {step_index} reuses a physical execution unexpectedly in this matrix"
            )
        all_runtime_execution_ids.update(runtime_ids)

        semantic_map = _identity_map(step_output)
        if set(semantic_map) != search_ids:
            missing = sorted(search_ids - set(semantic_map))
            added = sorted(set(semantic_map) - search_ids)
            raise RuntimeError(
                f"Step {step_index} changed the candidate population during retrieval: "
                f"missing={missing!r}, added={added!r}"
            )

        own_ids = _own_execution_ids_by_identity(step_output)
        for identity in search_ids:
            cumulative_execution_ids[identity].update(own_ids.get(identity, set()))
            actual = _portfolio_execution_ids(semantic_map[identity])
            expected = cumulative_execution_ids[identity]
            if actual != expected:
                raise RuntimeError(
                    f"Step {step_index} semantic material provenance mismatch for {identity!r}: "
                    f"expected cumulative execution IDs={sorted(expected)!r}, "
                    f"actual={sorted(actual)!r}"
                )

    detail = (
        f"{len(search_ids)} candidate(s), {len(normalized.steps)} cumulative semantic views, "
        f"{len(all_runtime_execution_ids)} occurrence-local physical executions"
    )
    return expected_found, detail


def _exception_status(error: Exception) -> Status:
    text = f"{type(error).__name__}: {error}"
    if any(pattern.search(text) for pattern in _AUTH_PATTERNS):
        return "SKIP"
    if any(pattern.search(text) for pattern in _TRANSIENT_PATTERNS):
        return "UNAVAILABLE"
    if isinstance(error, ModuleNotFoundError):
        return "SKIP"
    return "FAIL"


def _print_plan(scenario: MatrixScenario, dsl: str, run) -> None:
    print(f"=== {scenario.name} ===")
    print(scenario.description)
    print("DSL:")
    for line in dsl.rstrip().splitlines():
        print(f"  {line}")
    print("plan:")
    for step_run in run.steps:
        for plan_index, plan in enumerate(step_run.endpoint_plans):
            print(
                f"  Step {step_run.step_index} plan {plan_index}: "
                f"{plan.broker}/{plan.origin}/{plan.endpoint} "
                f"candidate={plan.candidate_input_from!r} "
                f"same_step_candidate={plan.candidate_input_from_plan!r} "
                f"material={step_run.material_input_from!r}"
            )


def run_scenario(
    scenario: MatrixScenario,
    *,
    ra: float,
    dec: float,
    radius_arcsec: float,
    expected_object_id: str | None,
    plan_only: bool,
) -> ScenarioOutcome:
    try:
        dsl, workflow, run = compile_and_plan(
            scenario,
            ra=ra,
            dec=dec,
            radius_arcsec=radius_arcsec,
        )
        assert_plan_contract(scenario, workflow, run)
        _print_plan(scenario, dsl, run)
    except Exception as error:
        return ScenarioOutcome(scenario, "FAIL", f"plan contract: {type(error).__name__}: {error}")

    if plan_only:
        return ScenarioOutcome(scenario, "PASS", "plan contract passed; no provider APIs contacted")

    missing = tuple(name for name in scenario.required_env if not os.environ.get(name))
    if missing:
        return ScenarioOutcome(
            scenario,
            "SKIP",
            "missing credential(s): " + ", ".join(missing),
        )

    try:
        registry = EndpointRegistry()
        executor = RegistryEndpointExecutor(registry=registry)
        staged = execute_staged_workflow_run(
            run,
            registry,
            executor,
            validate_semantic_model=True,
        )
        expected_found, detail = assert_live_material_contract(
            staged,
            expected_object_id=expected_object_id,
        )

        print("live semantic views:")
        for step_output in staged.normalized.steps:
            identities = sorted(_identity_map(step_output))
            physical_ids = [execution.execution_id for execution in step_output.executions]
            semantic_counts = dict(sorted(_semantic_types(step_output).items()))
            print(
                f"  Step {step_output.step_index}: identities={identities!r} "
                f"own_execution_ids={physical_ids!r}"
            )
            print(f"    semantic_types={semantic_counts!r}")
        print(f"  {detail}")

        if not expected_found:
            return ScenarioOutcome(
                scenario,
                "INCONCLUSIVE",
                f"material contract passed, but expected ztf/{expected_object_id} was not discovered",
            )
        return ScenarioOutcome(scenario, "PASS", detail)
    except Exception as error:
        return ScenarioOutcome(
            scenario,
            _exception_status(error),
            f"{type(error).__name__}: {error}",
        )


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run live cross-broker semantic material-lineage acceptance matrix."
    )
    parser.add_argument("--scenario", action="append", choices=[item.name for item in SCENARIOS])
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--ra", type=float, default=DEFAULT_RA)
    parser.add_argument("--dec", type=float, default=DEFAULT_DEC)
    parser.add_argument("--radius-arcsec", type=float, default=DEFAULT_RADIUS_ARCSEC)
    parser.add_argument(
        "--expect-object-id",
        default=DEFAULT_EXPECTED_OBJECT_ID,
        help="Expected ZTF identity in the tiny live cone; use an empty string to disable this check.",
    )
    return parser.parse_args()


def main() -> int:
    args = _args()
    if not 0.0 <= args.ra < 360.0:
        raise SystemExit("--ra must be in [0, 360)")
    if not -90.0 <= args.dec <= 90.0:
        raise SystemExit("--dec must be in [-90, 90]")
    if args.radius_arcsec <= 0.0:
        raise SystemExit("--radius-arcsec must be positive")

    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        load_dotenv = None
    if load_dotenv is not None:
        load_dotenv(override=False)

    if args.list:
        for scenario in SCENARIOS:
            print(f"{scenario.name}: {scenario.description}")
        return 0

    selected_names = set(args.scenario or ())
    selected = tuple(
        scenario
        for scenario in SCENARIOS
        if not selected_names or scenario.name in selected_names
    )
    expected_object_id = args.expect_object_id.strip() or None

    print("=== LIVE MATERIAL-LINEAGE MATRIX ===")
    print(
        f"cone=({args.ra}, {args.dec}, {args.radius_arcsec}arcsec) "
        f"expected_object={expected_object_id or 'disabled'}"
    )
    print()

    outcomes: list[ScenarioOutcome] = []
    for scenario in selected:
        outcome = run_scenario(
            scenario,
            ra=args.ra,
            dec=args.dec,
            radius_arcsec=args.radius_arcsec,
            expected_object_id=expected_object_id,
            plan_only=args.plan_only,
        )
        outcomes.append(outcome)
        print(f"RESULT: {outcome.status}: {outcome.detail}")
        print()

    print("=== MATRIX SUMMARY ===")
    counts = Counter(outcome.status for outcome in outcomes)
    for outcome in outcomes:
        print(f"{outcome.status:12} {outcome.scenario.name}: {outcome.detail}")
    print("counts:", dict(sorted(counts.items())))

    if counts.get("FAIL"):
        return 2
    if not counts.get("PASS"):
        return 3
    print("LIVE MATERIAL-LINEAGE MATRIX ACCEPTANCE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
