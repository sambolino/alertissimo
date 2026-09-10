#!/usr/bin/env python3
"""Focused live acceptance for the public DSL facade.

This proves the UI-facing entry points themselves, rather than reconstructing the
backend pipeline in the script:

    validate_dsl(text)  -> static parse/semantic/capability/lowering contract
    execute_dsl(text)   -> full plan/bind/execute/normalize/local-semantics turn

Run from the repository root::

    PYTHONPATH=. python scripts/live_dsl_api.py --validate-only
    PYTHONPATH=. python scripts/live_dsl_api.py
"""

from __future__ import annotations

import argparse

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.orchestration.normalization import summary_object_identity
from alertissimo.orchestration.runtime import StepRunState


DEFAULT_RA = 124.87996115142856
DEFAULT_DEC = -6.0205001
DEFAULT_RADIUS_ARCSEC = 1.0
DEFAULT_EXPECTED_OBJECT_ID = "ZTF20acpwljl"


def build_dsl(*, ra: float, dec: float, radius_arcsec: float) -> str:
    return (
        "objects from ztf via alerce\n"
        f"inside ({ra}, {dec}, {radius_arcsec}arcsec)\n"
        "latest 1\n"
        "with lightcurve via fink\n"
    )


def _print_dsl(dsl: str) -> None:
    print("DSL:")
    for line in dsl.rstrip().splitlines():
        print(f"  {line}")


def assert_static_contract(validation) -> None:
    if not validation.is_valid:
        raise RuntimeError(f"public validate_dsl rejected syntax/ontology: {validation!r}")
    if not validation.is_runnable or validation.compilation is None:
        raise RuntimeError(f"public validate_dsl did not produce runnable compilation: {validation!r}")
    operations = [step.op for step in validation.compilation.workflow.steps]
    if operations != ["cone_search", "get_lightcurve"]:
        raise RuntimeError(f"unexpected public validation workflow operations: {operations!r}")


def assert_live_contract(execution, *, expected_object_id: str) -> str:
    if [step.op for step in execution.workflow.steps] != ["cone_search", "get_lightcurve"]:
        raise RuntimeError(
            f"unexpected execution workflow operations: "
            f"{[step.op for step in execution.workflow.steps]!r}"
        )
    if len(execution.result.steps) != 2:
        raise RuntimeError(
            f"expected two occurrence-aligned semantic outputs, got {len(execution.result.steps)}"
        )
    if any(step.state is not StepRunState.SUCCEEDED for step in execution.run.steps):
        raise RuntimeError(
            f"public execution did not finish all Steps successfully: "
            f"{[step.state.value for step in execution.run.steps]!r}"
        )

    expected = ("ztf", expected_object_id)
    final_identities = {
        summary_object_identity(portfolio)
        for portfolio in execution.result.steps[-1].portfolios
    }
    if expected not in final_identities:
        raise RuntimeError(
            f"expected final Portfolio identity {expected!r}, found {sorted(final_identities)!r}"
        )

    downstream_binding = execution.staged.bindings[1]
    if len(downstream_binding.bound_calls) != 1:
        raise RuntimeError(
            f"expected one downstream Fink bound call, got {len(downstream_binding.bound_calls)}"
        )
    bound_values = tuple(downstream_binding.bound_calls[0].params.values())
    if not any(expected_object_id in str(value) for value in bound_values):
        raise RuntimeError(
            f"downstream facade execution did not bind {expected_object_id!r}: {bound_values!r}"
        )

    return (
        f"public execute_dsl completed 2 semantic Steps for ztf/{expected_object_id}; "
        "downstream Fink call was bound from the discovered Portfolio"
    )


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--ra", type=float, default=DEFAULT_RA)
    parser.add_argument("--dec", type=float, default=DEFAULT_DEC)
    parser.add_argument("--radius-arcsec", type=float, default=DEFAULT_RADIUS_ARCSEC)
    parser.add_argument("--expect-object-id", default=DEFAULT_EXPECTED_OBJECT_ID)
    return parser.parse_args()


def main() -> int:
    args = _args()
    dsl = build_dsl(
        ra=args.ra,
        dec=args.dec,
        radius_arcsec=args.radius_arcsec,
    )

    print("=== PUBLIC DSL API ACCEPTANCE ===")
    _print_dsl(dsl)

    try:
        validation = validate_dsl(dsl, name="public DSL API live acceptance")
        assert_static_contract(validation)
    except Exception as error:
        print(f"FAIL: validate_dsl: {type(error).__name__}: {error}")
        return 1

    if args.validate_only:
        print("PASS: validate_dsl produced a runnable compilation; no provider APIs contacted")
        return 0

    try:
        execution = execute_dsl(dsl, name="public DSL API live acceptance")
        detail = assert_live_contract(
            execution,
            expected_object_id=args.expect_object_id.strip(),
        )
    except Exception as error:
        print(f"FAIL: execute_dsl: {type(error).__name__}: {error}")
        return 1

    print(f"PASS: {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
