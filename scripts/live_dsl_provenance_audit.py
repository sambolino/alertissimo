#!/usr/bin/env python3
"""Audit end-to-end provenance on live accumulated DSL Portfolios.

This is a provenance probe, not a new provenance model. It reuses the cross-broker
material-lineage scenarios and distinguishes three honest provenance bases:

* payload-derived records: one ``InternalRecordSource`` identifies a raw payload surface;
* request-derived minimal identities: target binding proves an object identity even when
  the payload contains no summary row;
* execution-derived aggregates: one semantic record is collected from multiple raw
  payload surfaces belonging to one physical execution.

For source-less derived records, exact call ownership comes from the existing
``StepPortfolioResult.executions`` execution-local Portfolios. Consolidation preserves
record IDs, so that occurrence-local ownership remains valid in later cumulative views.
No fake raw-payload coordinate is invented for a multisurface aggregate.

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
from typing import Iterable, Literal, Mapping

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
_INTRINSIC_LIGHTCURVE_ARRAYS = frozenset(
    {
        "points",
        "forced_photometry_points",
        "magnitude_rate_points",
        "color_points",
        "feature_vector_points",
    }
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


def _step_record_execution_owners(step_output) -> dict[str, str]:
    """Map immutable record IDs to the physical execution group that produced them."""

    owners: dict[str, str] = {}
    for group in step_output.executions:
        for portfolio in group.portfolios:
            for record in portfolio.records:
                record_id = record.internal_record_id.value
                previous = owners.get(record_id)
                if previous is not None and previous != group.execution_id:
                    raise RuntimeError(
                        f"record {record_id!r} appears in multiple physical execution "
                        f"groups: {previous!r}, {group.execution_id!r}"
                    )
                owners[record_id] = group.execution_id
    return owners


def _cumulative_record_execution_owners(steps) -> dict[str, str]:
    owners: dict[str, str] = {}
    for step_output in steps:
        for record_id, execution_id in _step_record_execution_owners(step_output).items():
            previous = owners.get(record_id)
            if previous is not None and previous != execution_id:
                raise RuntimeError(
                    f"record {record_id!r} changes physical owner from {previous!r} "
                    f"to {execution_id!r}"
                )
            owners[record_id] = execution_id
    return owners


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
    """Recover target IDs from an execution's declarative endpoint contract."""

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


def _declared_owner_execution(
    record,
    executions,
    record_execution_owners: Mapping[str, str] | None,
):
    if record_execution_owners is None:
        return None
    execution_id = record_execution_owners.get(record.internal_record_id.value)
    if execution_id is None:
        return None
    execution = executions.get(execution_id)
    if execution is None:
        raise RuntimeError(
            f"record {record.internal_record_id.value} is owned by execution "
            f"{execution_id!r}, but that execution is absent from the Portfolio"
        )
    return execution


def _request_identity_execution(record, executions, *, declared_owner=None):
    """Resolve the deliberately source-less minimal summary identity."""

    if record.semantic_type.split("@", 1)[0] != "summary":
        return None
    if set(record.fields) != {"identity.object_id"}:
        return None
    object_id = record.get("identity.object_id")
    if object_id is None:
        return None

    origin, channel = _semantic_qualifiers(record.semantic_type)

    def matches(execution) -> bool:
        return (
            (origin is None or execution.origin == origin)
            and (channel is None or execution.broker == channel)
            and str(object_id) in _bound_target_ids(execution)
        )

    if declared_owner is not None:
        if not matches(declared_owner):
            raise RuntimeError(
                f"request-derived identity record {record.internal_record_id.value} "
                "has occurrence-local execution ownership inconsistent with its "
                "semantic identity or target binding"
            )
        return declared_owner

    candidates = [execution for execution in executions.values() if matches(execution)]
    if len(candidates) > 1:
        raise RuntimeError(
            f"request-derived identity record {record.internal_record_id.value} "
            f"({record.semantic_type}) matches multiple target-bound executions; "
            "occurrence-local ownership is required"
        )
    return candidates[0] if candidates else None


def _execution_aggregate_execution(
    record,
    executions,
    portfolio_identity,
    *,
    declared_owner=None,
):
    """Resolve a multisurface intrinsic-array aggregate to its owning execution."""

    if record.semantic_type.split("@", 1)[0] != "lightcurve":
        return None
    if not any(field in _INTRINSIC_LIGHTCURVE_ARRAYS for field in record.fields):
        return None
    if portfolio_identity is None:
        return None

    origin, channel = _semantic_qualifiers(record.semantic_type)
    portfolio_origin, object_id = portfolio_identity
    if origin is None or channel is None or str(origin) != str(portfolio_origin):
        return None

    def matches(execution) -> bool:
        return (
            execution.origin == origin
            and execution.broker == channel
            and str(object_id) in _bound_target_ids(execution)
        )

    if declared_owner is not None:
        if not matches(declared_owner):
            raise RuntimeError(
                f"execution-derived aggregate {record.internal_record_id.value} "
                "has occurrence-local execution ownership inconsistent with its "
                "semantic origin/channel or target binding"
            )
        return declared_owner

    candidates = [execution for execution in executions.values() if matches(execution)]
    if len(candidates) > 1:
        raise RuntimeError(
            f"execution-derived aggregate {record.internal_record_id.value} "
            f"({record.semantic_type}) matches multiple target-bound executions; "
            "occurrence-local ownership is required"
        )
    return candidates[0] if candidates else None


def audit_portfolio(
    portfolio,
    *,
    secret_values: Iterable[str] = (),
    record_execution_owners: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Validate payload-, request-, and execution-derived provenance."""

    executions = _execution_map(portfolio)
    identity = summary_object_identity(portfolio)
    portfolio_identity = (
        (str(identity[0]), str(identity[1])) if identity is not None else None
    )

    referenced: Counter[str] = Counter()
    records_by_execution: Counter[str] = Counter()
    payload_records_by_execution: Counter[str] = Counter()
    request_records_by_execution: Counter[str] = Counter()
    aggregate_records_by_execution: Counter[str] = Counter()
    semantic_types_by_execution: dict[str, Counter[str]] = defaultdict(Counter)

    for record in portfolio.records:
        source = record.internal_source
        declared_owner = _declared_owner_execution(
            record,
            executions,
            record_execution_owners,
        )

        if source is None:
            execution = _request_identity_execution(
                record,
                executions,
                declared_owner=declared_owner,
            )
            basis = "request"
            if execution is None:
                execution = _execution_aggregate_execution(
                    record,
                    executions,
                    portfolio_identity,
                    declared_owner=declared_owner,
                )
                basis = "aggregate"
            if execution is None:
                raise RuntimeError(
                    f"source-less record {record.internal_record_id.value} "
                    f"({record.semantic_type}) is neither a traceable request-derived "
                    "minimal identity nor an execution-derived intrinsic-array aggregate"
                )

            execution_id = execution.internal_execution_id.value
            referenced[execution_id] += 1
            records_by_execution[execution_id] += 1
            if basis == "request":
                request_records_by_execution[execution_id] += 1
            else:
                aggregate_records_by_execution[execution_id] += 1
            semantic_types_by_execution[execution_id][record.semantic_type] += 1
            continue

        execution_id = source.internal_execution_id.value
        execution = executions.get(execution_id)
        if execution is None:
            raise RuntimeError(
                f"record {record.internal_record_id.value} references missing execution "
                f"{execution_id!r}"
            )
        if declared_owner is not None and declared_owner is not execution:
            if declared_owner.internal_execution_id.value != execution_id:
                raise RuntimeError(
                    f"record {record.internal_record_id.value} InternalRecordSource "
                    f"points to {execution_id!r}, but occurrence-local ownership is "
                    f"{declared_owner.internal_execution_id.value!r}"
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
        "aggregate_records_by_execution": aggregate_records_by_execution,
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
    cumulative_owners: dict[str, str] = {}

    for step_index, identities in enumerate(step_maps):
        for record_id, execution_id in _step_record_execution_owners(steps[step_index]).items():
            previous = cumulative_owners.get(record_id)
            if previous is not None and previous != execution_id:
                raise RuntimeError(
                    f"record {record_id!r} changes physical owner from {previous!r} "
                    f"to {execution_id!r}"
                )
            cumulative_owners[record_id] = execution_id

        own_runtime_ids = set(staged.run.steps[step_index].execution_ids)
        own_group_ids = {
            group.execution_id for group in steps[step_index].executions
        }
        if own_runtime_ids != own_group_ids:
            raise RuntimeError(
                f"Step {step_index} runtime execution ownership differs from "
                "normalized execution groups"
            )

    for identity in sorted(candidate_ids):
        previous_records = {}
        previous_executions = {}

        for step_index, identities in enumerate(step_maps):
            # Only owners from this Step and earlier are valid for its snapshot.
            owners_through_step = _cumulative_record_execution_owners(
                steps[: step_index + 1]
            )
            portfolio = identities[identity]
            report = audit_portfolio(
                portfolio,
                secret_values=secret_values,
                record_execution_owners=owners_through_step,
            )
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
    aggregate_count = sum(
        sum(report["aggregate_records_by_execution"].values())
        for report in final_report.values()
    )

    detail = (
        f"{len(candidate_ids)} candidate(s); every final record resolves to an exact "
        "payload coordinate, a target-bound request, or its occurrence-local physical "
        "execution; inherited record/execution provenance remained immutable across "
        f"{len(steps)} Step views"
    )
    if aggregate_count:
        detail += (
            f"; {aggregate_count} aggregate record(s) retain exact execution ownership "
            "but collapse multiple raw payload coordinates"
        )
    if optional_gaps:
        detail += "; optional reproducibility metadata absent: " + ", ".join(optional_gaps)
    return expected_found, detail


def _print_audit(staged) -> None:
    final = staged.normalized.steps[-1]
    owners = _cumulative_record_execution_owners(staged.normalized.steps)
    print("final Portfolio provenance:")
    for identity, portfolio in sorted(_identity_map(final).items()):
        print(f"  {identity[0]}/{identity[1]}: {len(portfolio.records)} records")
        report = audit_portfolio(
            portfolio,
            secret_values=_known_secret_values(),
            record_execution_owners=owners,
        )
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
            aggregate_count = report["aggregate_records_by_execution"][execution_id]
            print(
                f"    {execution_id}: {execution.broker}/{execution.origin}/{execution.endpoint} "
                f"status={execution.status!r} transport={execution.transport!r} "
                f"method={execution.method!r} records={report['records_by_execution'][execution_id]}"
            )
            print(
                f"      provenance: payload_records={payload_count} "
                f"request_derived_records={request_count} "
                f"aggregate_derived_records={aggregate_count}"
            )
            if aggregate_count:
                print(
                    "      aggregate note: exact execution retained; multiple raw "
                    "payload coordinates collapsed at collection"
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
