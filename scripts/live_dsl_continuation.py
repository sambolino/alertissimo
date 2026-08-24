#!/usr/bin/env python3
"""Live incremental DSL Filter -> survivor-bound Get acceptance.

The first public-facade call discovers a bounded Lasair/ZTF candidate set and
materializes Fink evidence. The second call appends only::

    filter detection@ztf:fink.quality.real_bogus >= <threshold>
    with lightcurve via lasair

The acceptance proves that prior provider calls are replayed from the first result,
while the one genuinely new Lasair call is bound only to Filter survivors. Live data
may make the survivor set empty or unchanged; those cases are INCONCLUSIVE rather
than architecture failures.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any, Mapping

from dotenv import load_dotenv

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor
from alertissimo.orchestration.normalization import summary_object_identity


DEFAULT_RA = 124.87996115142856
DEFAULT_DEC = -6.0205001
DEFAULT_RADIUS_ARCSEC = 300.0
DEFAULT_THRESHOLD = 0.8


@dataclass(frozen=True)
class RecordedCall:
    broker: str
    origin: str
    endpoint: str
    params: dict[str, Any]


class RecordingEndpointExecutor:
    """Record calls reaching the real executor at the bound-call boundary."""

    def __init__(self, delegate: RegistryEndpointExecutor) -> None:
        self.delegate = delegate
        self.calls: list[RecordedCall] = []

    def execute(
        self,
        broker: str,
        origin: str,
        endpoint: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ):
        self.calls.append(
            RecordedCall(
                broker=broker,
                origin=origin,
                endpoint=endpoint,
                params=dict(params or {}),
            )
        )
        return self.delegate.execute(
            broker=broker,
            origin=origin,
            endpoint=endpoint,
            params=params,
            headers=headers,
        )


def _object_ids(step_output) -> tuple[str, ...]:
    found: list[str] = []
    for portfolio in step_output.portfolios:
        identity = summary_object_identity(portfolio)
        if identity is None:
            raise RuntimeError("Portfolio has no unambiguous summary object identity")
        origin, object_id = identity
        if origin != "ztf":
            raise RuntimeError(f"unexpected candidate origin: {origin!r}")
        if object_id not in found:
            found.append(object_id)
    return tuple(found)


def _bound_object_ids(params: Mapping[str, Any]) -> tuple[str, ...]:
    value = params.get("objectIds")
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item for item in value.split(",") if item)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return (str(value),)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ra", type=float, default=DEFAULT_RA)
    parser.add_argument("--dec", type=float, default=DEFAULT_DEC)
    parser.add_argument("--radius-arcsec", type=float, default=DEFAULT_RADIUS_ARCSEC)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    load_dotenv(override=False)

    first_source = f"""objects from ztf via lasair
inside ({args.ra}, {args.dec}, {args.radius_arcsec}arcsec)
with lightcurve via fink
"""
    continuation_source = f"""filter detection@ztf:fink.quality.real_bogus >= {args.threshold}
with lightcurve via lasair
"""

    print("=== FIRST PASS ===")
    print(first_source.rstrip())
    print()

    registry = EndpointRegistry()
    executor = RecordingEndpointExecutor(
        RegistryEndpointExecutor(registry=registry)
    )
    first = execute_dsl(
        first_source,
        name="live incremental continuation: first pass",
        registry=registry,
        executor=executor,
    )
    first_calls = tuple(executor.calls)

    if [step.op for step in first.workflow.steps] != [
        "cone_search",
        "get_lightcurve",
    ]:
        raise RuntimeError(
            f"unexpected first-pass workflow: {[step.op for step in first.workflow.steps]!r}"
        )
    if len(first_calls) != 2:
        raise RuntimeError(
            f"first pass expected two physical calls, observed {len(first_calls)}"
        )

    print("=== CONTINUATION ===")
    print(continuation_source.rstrip())
    print()

    validation = validate_dsl(continuation_source)
    if not validation.is_valid or not validation.is_runnable:
        raise RuntimeError(
            "continuation validation failed: "
            f"parse={validation.parse_error!r} "
            f"semantic={validation.semantic!r} "
            f"lowering={validation.lowering_error!r}"
        )
    if tuple(executor.calls) != first_calls:
        raise RuntimeError("continuation validation contacted a provider")

    second = execute_dsl(
        continuation_source,
        name="live incremental continuation: cumulative result",
        registry=registry,
        executor=executor,
    )
    new_calls = tuple(executor.calls[len(first_calls) :])

    if not second.source.startswith(first.source.rstrip() + "\n"):
        raise RuntimeError("continuation did not retain the active DSL workflow")

    expected_ops = [
        "cone_search",
        "get_lightcurve",
        "filter",
        "get_lightcurve",
    ]
    if [step.op for step in second.workflow.steps] != expected_ops:
        raise RuntimeError(
            f"unexpected cumulative workflow: {[step.op for step in second.workflow.steps]!r}"
        )
    if second.run.steps[2].execution_ids:
        raise RuntimeError("local FilterStep fabricated a physical execution")

    first_execution_ids = {
        execution.internal_execution_id.value
        for step in first.staged.execution.steps
        for execution in step.executions
    }
    replayed_execution_ids = {
        execution.internal_execution_id.value
        for step in second.staged.execution.steps[: len(first.staged.execution.steps)]
        for execution in step.executions
    }
    if replayed_execution_ids != first_execution_ids:
        raise RuntimeError("continuation did not preserve prior physical execution IDs")

    before_ids = _object_ids(first.result.steps[-1])
    survivor_ids = _object_ids(second.result.steps[2])
    downstream_ids = _object_ids(second.result.steps[3])

    print("=== INCREMENTAL PHYSICAL CALLS ===")
    print("Workflow state:   retained by execute_dsl")
    print(f"First-pass calls: {len(first_calls)}")
    for call in first_calls:
        print(f"  {call.broker}/{call.origin}/{call.endpoint} params={call.params}")
    print(f"New calls:        {len(new_calls)}")
    for call in new_calls:
        print(f"  {call.broker}/{call.origin}/{call.endpoint} params={call.params}")
    print()

    print("=== CANDIDATE FLOW ===")
    print(f"Fink materialized candidates: {len(before_ids)} {list(before_ids)}")
    print(f"Filter survivors:             {len(survivor_ids)} {list(survivor_ids)}")
    print(f"Lasair normalized objects:    {len(downstream_ids)} {list(downstream_ids)}")
    print()

    if not set(survivor_ids).issubset(before_ids):
        raise RuntimeError("Filter introduced identities absent from its input")

    if not survivor_ids:
        if new_calls:
            raise RuntimeError("empty Filter result still invoked the live executor")
        if second.run.steps[3].execution_ids:
            raise RuntimeError("empty downstream candidate set fabricated an execution")
        print("OK: empty Filter result made the continued Get vacuous")
        print("INCONCLUSIVE: live filter selected zero objects")
        return 3

    if len(new_calls) != 1:
        raise RuntimeError(
            "continuation must make exactly one new physical call for non-empty "
            f"survivors; observed {len(new_calls)}"
        )
    new_call = new_calls[0]
    if (new_call.broker, new_call.origin, new_call.endpoint) != (
        "lasair",
        "ztf",
        "lightcurves",
    ):
        raise RuntimeError(f"unexpected new continuation call: {new_call!r}")

    bound_ids = _bound_object_ids(new_call.params)
    if set(bound_ids) != set(survivor_ids):
        raise RuntimeError(
            "continued Lasair binding differs from Filter survivors: "
            f"bound={list(bound_ids)!r}, survivors={list(survivor_ids)!r}"
        )
    if set(downstream_ids) != set(survivor_ids):
        raise RuntimeError(
            "continued Lasair normalization differs from Filter survivors: "
            f"normalized={list(downstream_ids)!r}, survivors={list(survivor_ids)!r}"
        )

    print("OK: prior provider executions were replayed without live re-execution")
    print("OK: continued Lasair target binding equals the Filter survivor set")
    print("OK: downstream normalization preserves survivor identities")

    if set(survivor_ids) == set(before_ids):
        print("INCONCLUSIVE: live filter kept every candidate; narrowing was not exercised")
        return 3

    print(f"OK: Filter narrowed candidates from {len(before_ids)} to {len(survivor_ids)}")
    print()
    print("LIVE DSL CONTINUATION ACCEPTANCE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
