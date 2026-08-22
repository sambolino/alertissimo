#!/usr/bin/env python3
"""Live acceptance for adjacent ``where P`` proposition-quorum Confirm.

This complements ``live_dsl_confirm.py`` rather than replacing it::

    live_dsl_confirm.py
        -> bare ConfirmStep(predicate=None): cross-broker existence quorum

    live_dsl_confirm_predicate.py
        -> adjacent where P + ConfirmStep(predicate=P): proposition quorum

The live workflow is::

    ALeRCE ZTF cone discovery with P = exists(classification.best.class)
        -> Confirm P independently via Fink + Lasair (2-of-2)
        -> Fink lightcurve retrieval from Confirm survivors

The acceptance checks that:

* surface adjacency attaches the exact Search predicate to Confirm;
* Confirm plans only target-bound endpoints capable of materializing P;
* each broker's vote is evaluated on that broker's execution-local Portfolio;
* one broker contributes at most one vote;
* only proposition-quorum survivors bind the downstream provider call;
* Confirm owns only its real physical executions and invents no semantic record.

Provider/network failures are reported separately from architecture failures.

Run from the repository root::

    PYTHONPATH=. python scripts/live_dsl_confirm_predicate.py --plan-only
    PYTHONPATH=. python scripts/live_dsl_confirm_predicate.py
"""

from __future__ import annotations

import argparse
import re
from typing import Literal

from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import compile_surface_to_ir, parse_surface_script
from alertissimo.orchestration.ir import ConfirmStep
from alertissimo.orchestration.local_semantics import finalize_local_semantics
from alertissimo.orchestration.normalization import summary_object_identity
from alertissimo.orchestration.normalization.predicate import evaluate_portfolio_predicate
from alertissimo.orchestration.pipeline import execute_staged_workflow_run
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import CandidateInputRef, MaterialInputRef, StepRunState


Status = Literal["PASS", "INCONCLUSIVE", "UNAVAILABLE", "SKIP", "FAIL"]

DEFAULT_RA = 124.87996115142856
DEFAULT_DEC = -6.0205001
DEFAULT_RADIUS_ARCSEC = 1.0
DEFAULT_EXPECTED_OBJECT_ID = "ZTF20acpwljl"
DEFAULT_QUORUM = 2
CONFIRM_BROKERS = ("fink", "lasair")
PREDICATE_TEXT = "exists(classification.best.class)"

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


def build_dsl(*, ra: float, dec: float, radius_arcsec: float, quorum: int) -> str:
    brokers = ", ".join(CONFIRM_BROKERS)
    return (
        "objects from ztf via alerce\n"
        f"inside ({ra}, {dec}, {radius_arcsec}arcsec)\n"
        "latest 1\n"
        f"where {PREDICATE_TEXT}\n"
        f"confirm by {quorum} via {brokers}\n"
        "with lightcurve via fink\n"
    )


def compile_and_plan(*, ra: float, dec: float, radius_arcsec: float, quorum: int):
    graph = build_capability_graph()
    dsl = build_dsl(
        ra=ra,
        dec=dec,
        radius_arcsec=radius_arcsec,
        quorum=quorum,
    )
    workflow = compile_surface_to_ir(
        parse_surface_script(dsl),
        graph=graph,
        name="live Confirm proposition quorum",
    )
    run = plan_workflow(workflow, graph)
    return dsl, workflow, run


def assert_plan_contract(workflow, run) -> None:
    operations = [step.op for step in workflow.steps]
    if operations != ["cone_search", "confirm", "get_lightcurve"]:
        raise RuntimeError(f"unexpected workflow operations: {operations!r}")

    search_step, confirm_step, _downstream_step = workflow.steps
    if not isinstance(confirm_step, ConfirmStep):
        raise RuntimeError("Step 1 is not ConfirmStep")
    if search_step.predicate is None:
        raise RuntimeError("Search predicate was lost during lowering")
    if confirm_step.predicate is None:
        raise RuntimeError("adjacent where did not attach a proposition to Confirm")
    if confirm_step.predicate != search_step.predicate:
        raise RuntimeError("Confirm proposition differs from the canonical Search predicate")

    search_run, confirm_run, downstream_run = run.steps
    if search_run.endpoint_plans[0].candidate_input_from is not None:
        raise RuntimeError("Search physical plan unexpectedly has candidate input")

    if confirm_run.candidate_input_from is not None:
        raise RuntimeError(
            "Confirm StepRun must not overload candidate_input_from; physical candidate "
            "binding belongs on its EndpointPlans"
        )
    if confirm_run.material_input_from != MaterialInputRef(step_index=0):
        raise RuntimeError(
            f"Confirm material input mismatch: {confirm_run.material_input_from!r}"
        )
    if len(confirm_run.endpoint_plans) != len(CONFIRM_BROKERS):
        raise RuntimeError(
            f"expected {len(CONFIRM_BROKERS)} Confirm endpoint plans, got "
            f"{len(confirm_run.endpoint_plans)}"
        )
    actual_brokers = tuple(plan.broker for plan in confirm_run.endpoint_plans)
    if actual_brokers != CONFIRM_BROKERS:
        raise RuntimeError(
            f"Confirm broker plan order mismatch: expected {CONFIRM_BROKERS!r}, "
            f"got {actual_brokers!r}"
        )
    for plan in confirm_run.endpoint_plans:
        if plan.candidate_input_from != CandidateInputRef(step_index=0):
            raise RuntimeError(
                f"Confirm physical plan {plan.broker}/{plan.origin}/{plan.endpoint} "
                f"does not bind Search candidates: {plan.candidate_input_from!r}"
            )

    if downstream_run.endpoint_plans[0].candidate_input_from != CandidateInputRef(
        step_index=1
    ):
        raise RuntimeError("downstream physical plan does not bind Confirm survivors")
    if downstream_run.material_input_from != MaterialInputRef(step_index=1):
        raise RuntimeError("downstream Step does not inherit Confirm semantic material")


def _identity_map(step_output) -> dict[tuple[str, str], object]:
    result: dict[tuple[str, str], object] = {}
    for portfolio in step_output.portfolios:
        identity = summary_object_identity(portfolio)
        if identity is None:
            raise RuntimeError(
                f"Step {step_output.step_index} contains a Portfolio without one "
                "unambiguous summary identity"
            )
        normalized = (str(identity[0]), str(identity[1]))
        if normalized in result:
            raise RuntimeError(
                f"Step {step_output.step_index} contains duplicate identity {normalized!r}"
            )
        result[normalized] = portfolio
    return result


def _execution_broker(execution_group) -> str:
    execution_id = execution_group.execution_id
    found = {
        provenance.broker
        for portfolio in execution_group.portfolios
        for provenance in portfolio.executions
        if provenance.internal_execution_id.value == execution_id
    }
    if len(found) != 1:
        raise RuntimeError(
            f"Confirm execution {execution_id!r} does not resolve to one broker: "
            f"{sorted(found)!r}"
        )
    return next(iter(found))


def _attesting_brokers(confirm_step: ConfirmStep, confirm_output, identity: tuple[str, str]) -> set[str]:
    if confirm_step.predicate is None:
        raise RuntimeError("predicate live acceptance received bare ConfirmStep")

    brokers: set[str] = set()
    for execution_group in confirm_output.executions:
        broker = _execution_broker(execution_group)
        if broker not in CONFIRM_BROKERS:
            raise RuntimeError(f"unexpected Confirm execution broker {broker!r}")
        if any(
            summary_object_identity(portfolio) == identity
            and evaluate_portfolio_predicate(portfolio, confirm_step.predicate)
            for portfolio in execution_group.portfolios
        ):
            brokers.add(broker)
    return brokers


def assert_live_contract(
    workflow,
    staged,
    finalized,
    *,
    expected_object_id: str,
    quorum: int,
) -> tuple[bool, str]:
    identity = ("ztf", expected_object_id)
    search_map = _identity_map(finalized.steps[0])
    if identity not in search_map:
        return False, (
            f"expected candidate {identity!r} was not discovered while satisfying "
            f"{PREDICATE_TEXT}"
        )

    confirm_step = workflow.steps[1]
    if not isinstance(confirm_step, ConfirmStep) or confirm_step.predicate is None:
        raise RuntimeError("workflow Step 1 is not proposition Confirm")

    confirm_run = finalized.run.steps[1]
    confirm_output = finalized.steps[1]
    if confirm_run.state is not StepRunState.SUCCEEDED:
        raise RuntimeError(
            f"Confirm runtime state is {confirm_run.state.value!r}, expected succeeded"
        )
    if len(confirm_run.execution_ids) != len(CONFIRM_BROKERS):
        raise RuntimeError(
            f"Confirm owns {len(confirm_run.execution_ids)} physical executions; "
            f"expected {len(CONFIRM_BROKERS)}"
        )
    normalized_execution_ids = {
        execution.execution_id for execution in confirm_output.executions
    }
    if normalized_execution_ids != set(confirm_run.execution_ids):
        raise RuntimeError(
            "Confirm normalized execution ownership does not match runtime execution IDs"
        )

    attesting = _attesting_brokers(confirm_step, confirm_output, identity)
    confirmed = identity in _identity_map(confirm_output)
    if len(attesting) >= quorum and not confirmed:
        raise RuntimeError(
            f"{len(attesting)} brokers satisfy {PREDICATE_TEXT!r} for {identity!r}, "
            "but Confirm filtered it out"
        )
    if len(attesting) < quorum and confirmed:
        raise RuntimeError(
            f"only {len(attesting)} brokers satisfy {PREDICATE_TEXT!r} for {identity!r}, "
            "but Confirm retained it"
        )

    downstream_output = finalized.steps[2]
    downstream_map = _identity_map(downstream_output)
    downstream_binding = staged.bindings[2]

    if not confirmed:
        if downstream_binding.bound_calls:
            raise RuntimeError("downstream provider call ran despite failed proposition quorum")
        if downstream_map:
            raise RuntimeError("downstream semantic view is non-empty below proposition quorum")
        return False, (
            f"candidate discovered but only {len(attesting)}/{quorum} required brokers "
            f"satisfied {PREDICATE_TEXT}: {sorted(attesting)!r}"
        )

    if identity not in downstream_map:
        raise RuntimeError("proposition-confirmed candidate did not propagate downstream")
    if len(downstream_binding.bound_calls) != 1:
        raise RuntimeError(
            f"expected one downstream bound call, got {len(downstream_binding.bound_calls)}"
        )
    bound_values = set(downstream_binding.bound_calls[0].params.values())
    if expected_object_id not in bound_values and not any(
        expected_object_id in str(value) for value in bound_values
    ):
        raise RuntimeError(
            "downstream provider call does not contain the proposition-confirmed object identity"
        )

    if any(
        record.semantic_type.startswith("confirmation")
        for portfolio in confirm_output.portfolios
        for record in portfolio.records
    ):
        raise RuntimeError("Confirm invented a confirmation semantic record")

    return True, (
        f"{identity[0]}/{identity[1]} satisfied {PREDICATE_TEXT!r} at "
        f"{len(attesting)} broker(s) {sorted(attesting)!r}; downstream bound only "
        "the proposition-Confirm survivor"
    )


def _exception_status(error: Exception) -> Status:
    text = f"{type(error).__name__}: {error}"
    if any(pattern.search(text) for pattern in _AUTH_PATTERNS):
        return "SKIP"
    if any(pattern.search(text) for pattern in _TRANSIENT_PATTERNS):
        return "UNAVAILABLE"
    if isinstance(error, ModuleNotFoundError):
        return "SKIP"
    return "FAIL"


def _print_plan(dsl: str, run) -> None:
    print("DSL:")
    for line in dsl.rstrip().splitlines():
        print(f"  {line}")
    print("plan:")
    for step_run in run.steps:
        plans = step_run.endpoint_plans
        if not plans:
            print(
                f"  Step {step_run.step_index}: local; "
                f"candidate={step_run.candidate_input_from!r} "
                f"material={step_run.material_input_from!r}"
            )
            continue
        for plan_index, plan in enumerate(plans):
            print(
                f"  Step {step_run.step_index}/{plan_index}: "
                f"{plan.broker}/{plan.origin}/{plan.endpoint} "
                f"candidate={plan.candidate_input_from!r} "
                f"material={step_run.material_input_from!r}"
            )


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run live adjacent-where proposition Confirm acceptance."
    )
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--ra", type=float, default=DEFAULT_RA)
    parser.add_argument("--dec", type=float, default=DEFAULT_DEC)
    parser.add_argument("--radius-arcsec", type=float, default=DEFAULT_RADIUS_ARCSEC)
    parser.add_argument("--quorum", type=int, default=DEFAULT_QUORUM)
    parser.add_argument("--expect-object-id", default=DEFAULT_EXPECTED_OBJECT_ID)
    return parser.parse_args()


def main() -> int:
    args = _args()
    if not 0.0 <= args.ra < 360.0:
        raise SystemExit("--ra must be in [0, 360)")
    if not -90.0 <= args.dec <= 90.0:
        raise SystemExit("--dec must be in [-90, 90]")
    if args.radius_arcsec <= 0.0:
        raise SystemExit("--radius-arcsec must be positive")
    if not 1 <= args.quorum <= len(CONFIRM_BROKERS):
        raise SystemExit(
            f"--quorum must be between 1 and {len(CONFIRM_BROKERS)}"
        )
    expected_object_id = args.expect_object_id.strip()
    if not expected_object_id:
        raise SystemExit("--expect-object-id must be non-empty")

    print("=== LIVE CONFIRM PREDICATE QUORUM ===")
    print(
        f"cone=({args.ra}, {args.dec}, {args.radius_arcsec}arcsec) "
        f"expected_object={expected_object_id} quorum={args.quorum}/{len(CONFIRM_BROKERS)} "
        f"predicate={PREDICATE_TEXT}"
    )

    try:
        dsl, workflow, run = compile_and_plan(
            ra=args.ra,
            dec=args.dec,
            radius_arcsec=args.radius_arcsec,
            quorum=args.quorum,
        )
        assert_plan_contract(workflow, run)
        _print_plan(dsl, run)
    except Exception as error:
        print(f"FAIL: plan contract: {type(error).__name__}: {error}")
        return 1

    if args.plan_only:
        print("PASS: predicate-Confirm plan contract passed; no provider APIs contacted")
        return 0

    try:
        registry = EndpointRegistry()
        executor = RegistryEndpointExecutor(registry=registry)
        staged = execute_staged_workflow_run(
            run,
            registry,
            executor,
            validate_semantic_model=True,
        )
        finalized = finalize_local_semantics(staged.normalized)
        confirmed, detail = assert_live_contract(
            workflow,
            staged,
            finalized,
            expected_object_id=expected_object_id,
            quorum=args.quorum,
        )
    except Exception as error:
        status = _exception_status(error)
        print(f"{status}: {type(error).__name__}: {error}")
        return 1

    if not confirmed:
        print(f"INCONCLUSIVE: {detail}")
        return 3

    print(f"PASS: {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
