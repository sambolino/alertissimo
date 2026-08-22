#!/usr/bin/env python3
"""Audit end-to-end provenance on live accumulated DSL Portfolios.

This is a provenance probe, not a new provenance model. It reuses the cross-broker
material-lineage scenarios and asks whether each final semantic record can be traced
either to a physical execution plus raw-payload location, or (for the deliberately
synthesized minimal summary identity) to one unique target-bound request execution,
while inherited evidence remains unchanged across Step snapshots.

Run from the repository root::

    PYTHONPATH=. python scripts/live_dsl_provenance_audit.py

Useful options::

    PYTHONPATH=. python scripts/live_dsl_provenance_audit.py --list
    PYTHONPATH=. python scripts/live_dsl_provenance_audit.py --scenario alerce-search-fink-lasair
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import os
from typing import Iterable, Literal

from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor
from alertissimo.orchestration.normalization import summary_object_identity
from alertissimo.orchestration.pipeline import execute_staged_workflow_run

from scripts.live_dsl_material_lineage import (
    DEFAULT_DEC,
    DEFAULT_EXPECTED_OBJECT_ID,
    DEFAULT_RA,
    DEFAULT_RADIUS_ARCSEC,
    SCENARIOS,
    MatrixScenario,
    _exception_status,
    assert_plan_contract,
    compile_and_plan,
)


Status = Literal["PASS", "INCONCLUSIVE", "UNAVAILABLE", "SKIP", "FAIL"]
OPTIONAL_REPRO_FIELDS = (
    "payload_fingerprint",
    "registry_version",
    "adapter_version",
)


@dataclass(frozen=True)
class ProvenanceOutcome:
    scenario: MatrixScenario
    status: Status
    detail: str


def _identity_map(step_output):
    result = {}
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
                f"Step {step_output.step_index} contains duplicate semantic identity "
                f"{normalized!r} after consolidation"
            )
        result[normalized] = portfolio
    return result


def _execution_map(portfolio):
    return {
        execution.internal_execution_id.value: execution
        for execution in portfolio.executions
    }


def _record_map(portfolio):
    return {
        record.internal_record_id.value: record
        for record in portfolio.records
    }


def _semantic_qualifiers(semantic_type: str) -> tuple[str | None, str | None]:
    _family, at, qualifier = semantic_type.partition("@")
    if not at:
        return None, None
    producer, colon, channel = qualifier.partition(":")
    return producer or None, (channel or None) if colon else None


def _semantic_channel(semantic_type: str) -> str | None:
    return _semantic_qualifiers(semantic_type)[1]


def _known_secret_values() -> tuple[str, ...]:
    names = (
        "LASAIR_ZTF_TOKEN",
        "LASAIR_LSST_TOKEN",
    )
    return tuple(value for name in names if (value := os.environ.get(name)))


def _bound_target_ids(execution) -> tuple[str, ...]:
    """Recover target IDs from the execution's declarative endpoint contract."""

    try:
        spec = EndpointRegistry().resolve(
            execution.broker,
            execution.origin,
            execution.endpoint,
        )
    except (FileNotFoundError, KeyError):
        return ()

    values: list[str] = []
    for physical_name, declaration in spec.params.items():
        declaration = declaration or {}
        if declaration.get("bind") != "target_id":
            continue
        if physical_name not in execution.params:
            continue
        raw_value = execution.params[physical_name]
        collection = (declaration.get("binding") or {}).get("collection")
        if collection == "csv" and isinstance(raw_value, str):
            candidates = tuple(
                item.strip() for item in raw_value.split(",") if item.strip()
            )
        elif isinstance(raw_value, (list, tuple)):
            candidates = tuple(raw_value)
        else:
            candidates = (raw_value,)
        for candidate in candidates:
            if candidate is None or isinstance(candidate, bool):
                continue
            value = str(candidate)
            if value not in values:
                values.append(value)
    return tuple(values)


def _request_identity_execution(record, executions):
    """Resolve the one allowed source-less record form to its request execution.

    ``record_builder._complete_minimal_summary_identity`` deliberately synthesizes
    only ``summary@origin:broker.identity.object_id`` from positive target-binding
    evidence when a target-bound payload has no summary record of its own. That
    record has no ``InternalRecordSource`` because there is no raw payload coordinate.
    The audit accepts it only when exactly one stored execution's declarative
    target-id binding proves the same object identity.
    """

    if record.semantic_type.split("@", 1)[0] != "summary":
        return None
    if set(record.fields) != {"identity.object_id"}:
        return None
    object_id = record.get("identity.object_id")
    if object_id is None:
        return None

    origin, channel = _semantic_qualifiers(record.semantic_type)
    matches = []
    for execution in executions.values():
        if origin is not None and execution.origin != origin:
            continue
        if channel is not None and execution.broker != channel:
            continue
        if str(object_id) in _bound_target_ids(execution):
            matches.append(execution)

    if len(matches) > 1:
        raise RuntimeError(
            f"request-derived identity record {record.internal_record_id.value} "
            f"({record.semantic_type}) matches multiple target-bound executions; "
            "exact call provenance is ambiguous"
        )
    return matches[0] if matches else None


def audit_portfolio(portfolio, *, secret_values: Iterable[str] = ()) -> dict[str, object]:
    """Validate payload- and request-derived provenance inside one Portfolio."""

    executions = _execution_map(portfolio)
    referenced: Counter[str] = Counter()
    records_by_execution: Counter[str] = Counter()
    payload_records_by_execution: Counter[str] = Counter()
    request_records_by_execution: Counter[str] = Counter()
    semantic_types_by_execution: dict[str, Counter[str]] = defaultdict(Counter)

    for record in portfolio.records:
        source = record.internal_source
        if source is None:
            execution = _request_identity_execution(record, executions)
            if execution is None:
                raise RuntimeError(
                    f"source-less record {record.internal_record_id.value} "
                    f"({record.semantic_type}) is not a uniquely traceable "
                    "request-derived minimal summary identity"
                )
            execution_id = execution.internal_execution_id.value
            referenced[execution_id] += 1
            records_by_execution[execution_id] += 1
            request_records_by_execution[execution_id] += 1
            semantic_types_by_execution[execution_id][record.semantic_type] += 1
            continue

        execution_id = source.internal_execution_id.value
        execution = executions.get(execution_id)
        if execution is None:
            raise RuntimeError(
                f"record {record.internal_record_id.value} references missing execution "
                f"{execution_id!r}"
            )
        if source.payload_index is not None and source.payload_index < 0:
            raise RuntimeError(
                f"record {record.internal_record_id.value} has negative payload_index"
            )

        channel = _semantic_channel(record.semantic_type)
        if channel is not None and channel != execution.broker:
            raise RuntimeError(
                f"record {record.internal_record_id.value} semantic channel {channel!r} "
                f"does not match source execution broker {execution.broker!r}"
            )

        referenced[execution_id] += 1
        records_by_execution[execution_id] += 1
        payload_records_by_execution[execution_id] += 1
        semantic_types_by_execution[execution_id][record.semantic_type] += 1

    for edge in portfolio.edges:
        source = edge.internal_source
        if source is None:
            # Local semantic edges such as Match relations legitimately have no
            # provider payload source. This audit only requires referential integrity
            # when an edge claims an InternalRecordSource.
            continue
        execution_id = source.internal_execution_id.value
        if execution_id not in executions:
            raise RuntimeError(
                f"edge {edge.internal_edge_id.value} references missing execution "
                f"{execution_id!r}"
            )
        referenced[execution_id] += 1

    unreferenced = sorted(set(executions) - set(referenced))
    if unreferenced:
        raise RuntimeError(
            "Portfolio stores physical executions that no record/edge provenance "
            "references: " + ", ".join(unreferenced)
        )

    secrets = tuple(value for value in secret_values if value)
    for execution in executions.values():
        headers = execution.sanitized_headers or {}
        for name, value in headers.items():
            text = str(value)
            if any(secret in text for secret in secrets):
                raise RuntimeError(
                    f"execution {execution.internal_execution_id.value} leaks a known "
                    f"credential through sanitized header {name!r}"
                )

    missing_optional = {
        execution_id: tuple(
            field
            for field in OPTIONAL_REPRO_FIELDS
            if getattr(execution, field) is None
        )
        for execution_id, execution in executions.items()
    }

    return {
        "execution_count": len(executions),
        "record_count": len(portfolio.records),
        "edge_count": len(portfolio.edges),
        "records_by_execution": records_by_execution,
        "payload_records_by_execution": payload_records_by_execution,
        "request_records_by_execution": request_records_by_execution,
        "semantic_types_by_execution": semantic_types_by_execution,
        "missing_optional": missing_optional,
    }


def audit_accumulation(staged, *, expected_object_id: str | None) -> tuple[bool, str]:
    """Prove that accumulated Step snapshots preserve provenance immutably."""

    steps = staged.normalized.steps
    if not steps:
        raise RuntimeError("workflow produced no normalized Step outputs")

    step_maps = [_identity_map(step) for step in steps]
    if not step_maps[0]:
        return False, "live discovery returned no semantic Portfolios"

    candidate_ids = set(step_maps[0])
    for step_index, identities in enumerate(step_maps[1:], start=1):
        if set(identities) != candidate_ids:
            raise RuntimeError(
                f"Step {step_index} candidate population differs from Search during "
                "provenance audit"
            )

    expected_identity = (
        ("ztf", str(expected_object_id)) if expected_object_id is not None else None
    )
    expected_found = expected_identity is None or expected_identity in candidate_ids

    secret_values = _known_secret_values()
    final_report: dict[tuple[str, str], dict[str, object]] = {}

    for identity in sorted(candidate_ids):
        previous_records = {}
        previous_executions = {}

        for step_index, identities in enumerate(step_maps):
            portfolio = identities[identity]
            report = audit_portfolio(portfolio, secret_values=secret_values)
            records = _record_map(portfolio)
            executions = _execution_map(portfolio)

            missing_records = sorted(set(previous_records) - set(records))
            if missing_records:
                raise RuntimeError(
                    f"Step {step_index} dropped inherited records for {identity!r}: "
                    f"{missing_records!r}"
                )
            for record_id, previous in previous_records.items():
                if records[record_id] != previous:
                    raise RuntimeError(
                        f"Step {step_index} mutated inherited record {record_id!r} "
                        f"for {identity!r}"
                    )

            missing_executions = sorted(set(previous_executions) - set(executions))
            if missing_executions:
                raise RuntimeError(
                    f"Step {step_index} dropped inherited execution provenance for "
                    f"{identity!r}: {missing_executions!r}"
                )
            for execution_id, previous in previous_executions.items():
                if executions[execution_id] != previous:
                    raise RuntimeError(
                        f"Step {step_index} mutated inherited execution provenance "
                        f"{execution_id!r} for {identity!r}"
                    )

            own_runtime_ids = set(staged.run.steps[step_index].execution_ids)
            own_group_ids = {
                group.execution_id for group in steps[step_index].executions
            }
            if own_runtime_ids != own_group_ids:
                raise RuntimeError(
                    f"Step {step_index} runtime execution ownership differs from "
                    "normalized execution groups"
                )

            previous_records = records
            previous_executions = executions
            if step_index == len(steps) - 1:
                final_report[identity] = report

    optional_gaps = sorted(
        {
            field
            for report in final_report.values()
            for missing in report["missing_optional"].values()
            for field in missing
        }
    )
    detail = (
        f"{len(candidate_ids)} candidate(s); every final record resolves either to "
        "a stored physical execution + raw payload coordinate or to one uniquely "
        "matching target-bound request; inherited record/execution provenance "
        f"remained immutable across {len(steps)} Step views"
    )
    if optional_gaps:
        detail += "; optional reproducibility metadata absent: " + ", ".join(optional_gaps)
    return expected_found, detail


def _print_audit(staged) -> None:
    final = staged.normalized.steps[-1]
    print("final Portfolio provenance:")
    for identity, portfolio in sorted(_identity_map(final).items()):
        print(f"  {identity[0]}/{identity[1]}: {len(portfolio.records)} records")
        report = audit_portfolio(portfolio, secret_values=_known_secret_values())
        executions = _execution_map(portfolio)
        for execution_id, execution in executions.items():
            types = report["semantic_types_by_execution"][execution_id]
            type_summary = ", ".join(
                f"{semantic_type}={count}"
                for semantic_type, count in sorted(types.items())
            )
            missing = report["missing_optional"][execution_id]
            payload_count = report["payload_records_by_execution"][execution_id]
            request_count = report["request_records_by_execution"][execution_id]
            print(
                f"    {execution_id}: {execution.broker}/{execution.origin}/{execution.endpoint} "
                f"status={execution.status!r} transport={execution.transport!r} "
                f"method={execution.method!r} records={report['records_by_execution'][execution_id]}"
            )
            print(
                f"      provenance: payload_records={payload_count} "
                f"request_derived_records={request_count}"
            )
            print(f"      semantic types: {type_summary or 'edge-only'}")
            print(
                f"      audit: started={execution.started_at is not None} "
                f"finished={execution.finished_at is not None} "
                f"elapsed={execution.elapsed_ms is not None} "
                f"response_status={execution.response_status_code!r} "
                f"raw_bytes={execution.raw_size_bytes!r}"
            )
            if missing:
                print(f"      optional missing: {', '.join(missing)}")


def run_scenario(
    scenario: MatrixScenario,
    *,
    ra: float,
    dec: float,
    radius_arcsec: float,
    expected_object_id: str | None,
) -> ProvenanceOutcome:
    try:
        dsl, workflow, run = compile_and_plan(
            scenario,
            ra=ra,
            dec=dec,
            radius_arcsec=radius_arcsec,
        )
        assert_plan_contract(scenario, workflow, run)
    except Exception as error:
        return ProvenanceOutcome(
            scenario,
            "FAIL",
            f"plan contract: {type(error).__name__}: {error}",
        )

    print(f"=== {scenario.name} ===")
    print(scenario.description)
    print("DSL:")
    for line in dsl.rstrip().splitlines():
        print(f"  {line}")

    missing = tuple(name for name in scenario.required_env if not os.environ.get(name))
    if missing:
        return ProvenanceOutcome(
            scenario,
            "SKIP",
            "missing credential(s): " + ", ".join(missing),
        )

    try:
        registry = EndpointRegistry()
        staged = execute_staged_workflow_run(
            run,
            registry,
            RegistryEndpointExecutor(registry=registry),
            validate_semantic_model=True,
        )
        expected_found, detail = audit_accumulation(
            staged,
            expected_object_id=expected_object_id,
        )
        _print_audit(staged)
        if not expected_found:
            return ProvenanceOutcome(
                scenario,
                "INCONCLUSIVE",
                f"provenance contract passed, but expected ztf/{expected_object_id} "
                "was not discovered",
            )
        return ProvenanceOutcome(scenario, "PASS", detail)
    except Exception as error:
        return ProvenanceOutcome(
            scenario,
            _exception_status(error),
            f"{type(error).__name__}: {error}",
        )


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit live cross-broker accumulated Portfolio provenance."
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=[item.name for item in SCENARIOS],
    )
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--ra", type=float, default=DEFAULT_RA)
    parser.add_argument("--dec", type=float, default=DEFAULT_DEC)
    parser.add_argument("--radius-arcsec", type=float, default=DEFAULT_RADIUS_ARCSEC)
    parser.add_argument(
        "--expect-object-id",
        default=DEFAULT_EXPECTED_OBJECT_ID,
        help="Expected ZTF identity in the tiny cone; empty string disables the check.",
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

    print("=== LIVE PROVENANCE AUDIT ===")
    print(
        f"cone=({args.ra}, {args.dec}, {args.radius_arcsec}arcsec) "
        f"expected_object={expected_object_id or 'disabled'}"
    )
    print()

    outcomes: list[ProvenanceOutcome] = []
    for scenario in selected:
        outcome = run_scenario(
            scenario,
            ra=args.ra,
            dec=args.dec,
            radius_arcsec=args.radius_arcsec,
            expected_object_id=expected_object_id,
        )
        outcomes.append(outcome)
        print(f"RESULT: {outcome.status}: {outcome.detail}")
        print()

    counts = Counter(outcome.status for outcome in outcomes)
    print("=== AUDIT SUMMARY ===")
    for outcome in outcomes:
        print(f"{outcome.status:<12} {outcome.scenario.name}: {outcome.detail}")
    print(f"counts: {dict(counts)!r}")

    if any(outcome.status == "FAIL" for outcome in outcomes):
        return 1
    if outcomes and all(outcome.status == "PASS" for outcome in outcomes):
        print("LIVE PROVENANCE AUDIT PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
