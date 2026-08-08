"""Validation for the human-authored minimal broker mapping schema.

This module deliberately validates structure, not semantic paths against the
feature catalog.  Run it as ``python -m ...mapping_schema FILE`` or with
``--all``.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any, Mapping

import yaml


MAPPING_KEYS = {"broker", "origin", "payloads", "mappings", "description", "notes"}
PAYLOAD_KEYS = {"path", "endpoint", "description"}
UNMAPPED_KEYS = {"broker", "origin", "unmapped", "notes"}
UNMAPPED_VALUE_KEYS = {"reason", "note", "candidate_meaning"}
OLD_HELPER_KEYS = {
    "availability",
    "field_status",
    "source_fields",
    "record_type",
    "object_summary",
    "sources",
    "attribute_inventory",
    "mapping_policy",
    "endpoints",
}


class SchemaValidationError(ValueError):
    """Raised when one or more mapping schema constraints are violated."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


def _load_yaml(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as stream:
            return yaml.safe_load(stream)
    except (OSError, yaml.YAMLError) as exc:
        raise SchemaValidationError([f"{path}: could not read YAML: {exc}"]) from exc


def _unsupported(data: Mapping[Any, Any], allowed: set[str], label: str) -> list[str]:
    return [f"{label}: unsupported top-level key {key!r}" for key in data if key not in allowed]


def _valid_payload_name(name: Any) -> bool:
    return (
        isinstance(name, str)
        and bool(name)
        and "#" not in name
        and not name.startswith(".")
        and not name.endswith(".")
        and not any(character.isspace() for character in name)
    )


def _raw_reference_error(reference: Any, payloads: Mapping[str, Any]) -> str | None:
    if not isinstance(reference, str):
        return "must be a string"
    if reference.count("#") != 1:
        return "must contain exactly one '#'"
    payload, field = reference.split("#")
    if payload != payload.strip() or field != field.strip():
        return "must not contain whitespace around the payload or raw field"
    if not payload or payload not in payloads:
        return f"references unknown payload {payload!r}"
    if not field:
        return "must have a non-empty raw field"
    return None


def validate_mapping_data(
    data: Any,
    *,
    label: str = "mappings.yaml",
    endpoint_names: set[str] | None = None,
) -> dict[str, Any]:
    """Validate parsed mappings data and return it when valid."""
    if not isinstance(data, dict):
        raise SchemaValidationError([f"{label}: top level must be a mapping"])
    errors = _unsupported(data, MAPPING_KEYS, label)
    payloads = data.get("payloads")
    if not isinstance(payloads, dict):
        errors.append(f"{label}: payloads must be a mapping")
        payloads = {}
    for payload_key, definition in payloads.items():
        prefix = f"{label}: payload {payload_key!r}"
        if not _valid_payload_name(payload_key):
            errors.append(f"{prefix}: invalid payload key")
        if not isinstance(definition, dict):
            errors.append(f"{prefix}: definition must be a mapping")
            continue
        for key in definition:
            if key not in PAYLOAD_KEYS:
                errors.append(f"{prefix}: unsupported key {key!r}")
        path = definition.get("path")
        if not isinstance(path, str) or not path:
            errors.append(f"{prefix}: path must be a non-empty string")
        endpoint = definition.get("endpoint", payload_key)
        if not isinstance(endpoint, str) or not endpoint:
            errors.append(f"{prefix}: endpoint must be a non-empty string")
        elif endpoint_names is not None and endpoint not in endpoint_names:
            errors.append(f"{prefix}: references unknown endpoint {endpoint!r}")
        if "description" in definition and not isinstance(definition["description"], str):
            errors.append(f"{prefix}: description must be a string")

    mappings = data.get("mappings")
    if not isinstance(mappings, dict):
        errors.append(f"{label}: mappings must be a mapping")
        mappings = {}
    for semantic_path, references in mappings.items():
        prefix = f"{label}: mapping {semantic_path!r}"
        if (
            not isinstance(semantic_path, str)
            or not semantic_path
            or "@" not in semantic_path
            or any(character.isspace() for character in semantic_path)
            or semantic_path in OLD_HELPER_KEYS
        ):
            errors.append(f"{prefix}: invalid qualified semantic path")
        if not isinstance(references, list):
            errors.append(f"{prefix}: value must be a list of raw references")
            continue
        for reference in references:
            problem = _raw_reference_error(reference, payloads)
            if problem:
                errors.append(f"{prefix}: raw reference {reference!r} {problem}")
    if errors:
        raise SchemaValidationError(errors)
    return data


def validate_unmapped_data(
    data: Any, mapping_data: Mapping[str, Any], *, label: str = "unmapped_fields.yaml"
) -> dict[str, Any]:
    """Validate a parsed unmapped-fields log against its mappings document."""
    if not isinstance(data, dict):
        raise SchemaValidationError([f"{label}: top level must be a mapping"])
    errors = _unsupported(data, UNMAPPED_KEYS, label)
    for identity in ("broker", "origin"):
        if data.get(identity) != mapping_data.get(identity):
            errors.append(f"{label}: {identity} does not match mappings.yaml")
    entries = data.get("unmapped")
    if not isinstance(entries, list):
        errors.append(f"{label}: unmapped must be a list")
        entries = []
    payloads = mapping_data.get("payloads", {})
    for index, entry in enumerate(entries):
        prefix = f"{label}: unmapped entry {index}"
        if not isinstance(entry, dict) or len(entry) != 1:
            errors.append(f"{prefix}: must be a one-entry mapping")
            continue
        reference, details = next(iter(entry.items()))
        problem = _raw_reference_error(reference, payloads)
        if problem:
            errors.append(f"{prefix}: raw reference {reference!r} {problem}")
        if not isinstance(details, dict):
            errors.append(f"{prefix}: value must be a mapping")
            continue
        for key in details:
            if key not in UNMAPPED_VALUE_KEYS:
                errors.append(f"{prefix}: unsupported value key {key!r}")
        reason = details.get("reason")
        if not isinstance(reason, str) or not reason:
            errors.append(f"{prefix}: reason must be a non-empty string")
        for key in ("note", "candidate_meaning"):
            if key in details and not isinstance(details[key], str):
                errors.append(f"{prefix}: {key} must be a string")
    if errors:
        raise SchemaValidationError(errors)
    return data


def validate_file(path: str | Path) -> None:
    """Validate mappings.yaml and its endpoint/unmapped sibling files."""
    mapping_path = Path(path)
    endpoint_path = mapping_path.with_name("endpoints.yaml")
    endpoint_names = None
    if endpoint_path.exists():
        endpoint_data = _load_yaml(endpoint_path)
        if not isinstance(endpoint_data, dict) or not isinstance(endpoint_data.get("endpoints"), dict):
            raise SchemaValidationError([f"{endpoint_path}: endpoints must be a mapping"])
        endpoint_names = set(endpoint_data["endpoints"])
    mapping_data = validate_mapping_data(
        _load_yaml(mapping_path), label=str(mapping_path), endpoint_names=endpoint_names
    )
    unmapped_path = mapping_path.with_name("unmapped_fields.yaml")
    if unmapped_path.exists():
        validate_unmapped_data(_load_yaml(unmapped_path), mapping_data, label=str(unmapped_path))


def _registry_root() -> Path:
    return Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate minimal broker mapping schemas")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("path", nargs="?", help="path to mappings.yaml")
    group.add_argument("--all", action="store_true", help="validate all minimal-schema registry mappings")
    args = parser.parse_args(argv)
    paths = sorted(_registry_root().glob("*/*/mappings.yaml")) if args.all else [Path(args.path)]
    failed = False
    for path in paths:
        try:
            data = _load_yaml(path)
            if args.all and (not isinstance(data, dict) or "payloads" not in data):
                print(f"SKIPPED {path}: legacy schema (no payloads)")
                continue
            validate_file(path)
            print(f"PASSED {path}")
        except SchemaValidationError as exc:
            failed = True
            for error in exc.errors:
                print(f"ERROR {error}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
