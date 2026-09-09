#!/usr/bin/env python3
"""Live acceptance for adjacent ``where P`` proposition-quorum Confirm.

This complements ``live_dsl_confirm.py``:

* ``live_dsl_confirm.py`` exercises bare existence quorum;
* this script exercises proposition quorum attached by immediate ``where`` adjacency.

The proposition deliberately uses the already-supported existence predicate syntax::

    where exists classification.best.class

That asks whether each Confirm broker independently materializes a classification
``best.class`` field for the exact candidate. It does not require Fink and Lasair
to use the same classification taxonomy.
"""

from __future__ import annotations

import argparse

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

from scripts import live_dsl_confirm as existence_live


DEFAULT_RA = existence_live.DEFAULT_RA
DEFAULT_DEC = existence_live.DEFAULT_DEC
DEFAULT_RADIUS_ARCSEC = 300.0
DEFAULT_EXPECTED_OBJECT_ID = None
DEFAULT_QUORUM = 2
CONFIRM_BROKERS = ("fink", "lasair")
PREDICATE_TEXT = "exists classification.best.class"


def build_dsl(*, ra: float, dec: float, radius_arcsec: float, quorum: int) -> str:
    brokers = ", ".join(CONFIRM_BROKERS)
    return (
        "objects from ztf via alerce\n"
        f"inside ({ra}, {dec}, {radius_arcsec}arcsec)\n"
        "latest 1\n"
        f"where {PREDICATE_TEXT}\n"
        f"confirm by {quorum} via {brokers}\n"
        "with lightcurve via alerce\n"
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
    search_plan = search_run.endpoint_plans[0]
    selection = search_plan.selection_realization
    if selection is None or selection.residual != search_step.selection:
        raise RuntimeError("latest selection has no normalized residual guarantee")
    if selection.pushdown is not None or selection.params:
        raise RuntimeError(
            "latest was unsafely pushed ahead of the residual existence predicate"
        )
    if confirm_run.candidate_input_from is not None:
        raise RuntimeError("Confirm StepRun must not carry physical candidate lineage")
    if confirm_run.material_input_from != MaterialInputRef(step_index=0):
        raise RuntimeError(
            f"Confirm material input mismatch: {confirm_run.material_input_from!r}"
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
                "does not bind Search candidates"
            )

    if downstream_run.endpoint_plans[0].candidate_input_from != CandidateInputRef(
        step_index=1
    ):
        raise RuntimeError("downstream physical plan does not bind Confirm survivors")
    if downstream_run.material_input_from != MaterialInputRef(step_index=1):
        raise RuntimeError("downstream Step does not inherit Confirm material")


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


def _predicate_attesting_brokers(
    confirm_step: ConfirmStep,
    confirm_output,
    identity: tuple[str, str],
) -> set[str]:
    if confirm_step.predicate is None:
        raise RuntimeError("predicate acceptance received bare ConfirmStep")

    votes: set[str] = set()
    for execution_group in confirm_output.executions:
        broker = _execution_broker(execution_group)
        if any(
            summary_object_identity(portfolio) == identity
            and evaluate_portfolio_predicate(portfolio, confirm_step.predicate)
            for portfolio in execution_group.portfolios
        ):
            votes.add(broker)
    return votes


def assert_live_contract(
    workflow,
    staged,
    finalized,
    *,
    expected_object_id: str | None,
    quorum: int,
) -> tuple[bool, str]:
    search_map = existence_live._identity_map(finalized.steps[0])
    if not search_map:
        return False, (
            f"no candidate in the cone satisfied {PREDICATE_TEXT!r}"
        )
    if len(search_map) != 1:
        raise RuntimeError(
            f"latest 1 exposed {len(search_map)} Search candidates instead of one"
        )
    identity = next(iter(search_map))
    if expected_object_id is not None and identity != ("ztf", expected_object_id):
        return False, (
            f"latest qualifying candidate was {identity!r}, not the optional "
            f"expected object {expected_object_id!r}"
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

    attesting = _predicate_attesting_brokers(confirm_step, confirm_output, identity)
    confirmed = identity in existence_live._identity_map(confirm_output)
    if len(attesting) >= quorum and not confirmed:
        raise RuntimeError(
            f"{len(attesting)} brokers satisfy {PREDICATE_TEXT!r}, but Confirm filtered "
            f"out {identity!r}"
        )
    if len(attesting) < quorum and confirmed:
        raise RuntimeError(
            f"only {len(attesting)} brokers satisfy {PREDICATE_TEXT!r}, but Confirm "
            f"retained {identity!r}"
        )

    downstream_map = existence_live._identity_map(finalized.steps[2])
    downstream_binding = staged.bindings[2]
    if not confirmed:
        if downstream_binding.bound_calls or downstream_map:
            raise RuntimeError("downstream was non-vacuous below proposition quorum")
        return False, (
            f"only {len(attesting)}/{quorum} brokers satisfied {PREDICATE_TEXT!r}: "
            f"{sorted(attesting)!r}"
        )

    if identity not in downstream_map:
        raise RuntimeError("proposition-confirmed candidate did not propagate downstream")
    if len(downstream_binding.bound_calls) != 1:
        raise RuntimeError(
            f"expected one downstream bound call, got {len(downstream_binding.bound_calls)}"
        )

    return True, (
        f"{identity[0]}/{identity[1]} satisfied {PREDICATE_TEXT!r} at "
        f"{len(attesting)} broker(s) {sorted(attesting)!r}; downstream bound only "
        "the proposition-Confirm survivor"
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
    if not 1 <= args.quorum <= len(CONFIRM_BROKERS):
        raise SystemExit(
            f"--quorum must be between 1 and {len(CONFIRM_BROKERS)}"
        )

    print("=== LIVE CONFIRM PREDICATE QUORUM ===")
    print(
        f"cone=({args.ra}, {args.dec}, {args.radius_arcsec}arcsec) "
        f"expected_object={args.expect_object_id} "
        f"quorum={args.quorum}/{len(CONFIRM_BROKERS)} predicate={PREDICATE_TEXT}"
    )

    try:
        dsl, workflow, run = compile_and_plan(
            ra=args.ra,
            dec=args.dec,
            radius_arcsec=args.radius_arcsec,
            quorum=args.quorum,
        )
        assert_plan_contract(workflow, run)
        existence_live._print_plan(dsl, run)
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
            expected_object_id=args.expect_object_id,
            quorum=args.quorum,
        )
    except Exception as error:
        status = existence_live._exception_status(error)
        print(f"{status}: {type(error).__name__}: {error}")
        return 1

    if not confirmed:
        print(f"INCONCLUSIVE: {detail}")
        return 3

    print(f"PASS: {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
