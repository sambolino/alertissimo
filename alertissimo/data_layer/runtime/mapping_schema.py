"""Validation for the human-authored minimal provider mapping schema."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml


class MappingSchemaError(ValueError):
    """Raised when a registry YAML file does not satisfy the minimal schema."""


MAPPING_KEYS = {
    "broker", "origin", "payloads", "mappings", "transforms", "description", "notes",
}
PAYLOAD_KEYS = {"path", "endpoint", "description", "row_filter"}
TRANSFORM_KEYS = {"type", "map", "default", "skip_null", "note"}
TRANSFORM_TYPES = {
    "boolean_not",
    "value_map",
    "jd_to_mjd",
    "to_string_strip",
    "to_float",
    "to_int",
}
UNMAPPED_KEYS = {"broker", "origin", "unmapped", "notes"}
UNMAPPED_VALUE_KEYS = {"reason", "note", "candidate_meaning"}
OLD_HELPER_KEYS = {
    "sources", "attribute_inventory", "mapping_policy", "availability",
    "source_fields", "field_status", "record_type", "object_summary", "endpoints",
}


def _load_yaml(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as stream:
            return yaml.safe_load(stream)
    except (OSError, yaml.YAMLError) as exc:
        raise MappingSchemaError(f"{path}: cannot read YAML: {exc}") from exc


def _mapping(value: Any, where: str) -> dict[Any, Any]:
    if not isinstance(value, dict):
        raise MappingSchemaError(f"{where} must be a mapping")
    return value


def _nonempty_string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MappingSchemaError(f"{where} must be a non-empty string")
    return value


def _allowed_keys(value: dict[Any, Any], allowed: set[str], where: str) -> None:
    unsupported = set(value) - allowed
    if unsupported:
        raise MappingSchemaError(f"{where} has unsupported key(s): {', '.join(map(str, sorted(unsupported, key=str)))}")


def _validate_payload_key(key: Any, where: str) -> str:
    key = _nonempty_string(key, where)
    if "#" in key or key.startswith(".") or key.endswith(".") or any(c.isspace() for c in key):
        raise MappingSchemaError(f"{where} is not a valid payload key: {key!r}")
    return key


def _validate_payload_path(value: Any, where: str) -> str:
    """Validate the deliberately small payload-root/path notation."""
    value = _nonempty_string(value, where)
    if value in (".", "[]"):
        return value
    path = value[3:] if value.startswith("[].") else value
    suffix = path[-2:] if path.endswith(("[]", "{}")) else ""
    collection_path = path[:-2] if suffix else path
    if (
        not suffix
        or not collection_path
        or "[]" in collection_path
        or "{}" in collection_path
        or any(
            not part or not part.replace("_", "a").isalnum()
            for part in collection_path.split(".")
        )
    ):
        raise MappingSchemaError(
            f"{where} must be '.' or a collection path ending in '[]' or '{{}}'"
        )
    return value


def _validate_raw_reference(reference: Any, payloads: set[str], where: str) -> None:
    if not isinstance(reference, str) or reference.count("#") != 1:
        raise MappingSchemaError(f"{where} must be a string containing exactly one '#'")
    payload_key, raw_field = reference.split("#")
    if not payload_key or not raw_field:
        raise MappingSchemaError(f"{where} must have non-empty payload and raw field parts")
    if payload_key != payload_key.strip() or raw_field != raw_field.strip():
        raise MappingSchemaError(f"{where} must not contain whitespace around either part")
    if payload_key not in payloads:
        raise MappingSchemaError(f"{where} references unknown payload {payload_key!r}")


def _validate_endpoints(path: Path, endpoints_used: list[tuple[str, str]]) -> None:
    if not path.exists():
        return
    document = _mapping(_load_yaml(path), str(path))
    endpoints = _mapping(document.get("endpoints"), f"{path}: endpoints")
    for payload_key, endpoint in endpoints_used:
        if endpoint not in endpoints:
            raise MappingSchemaError(
                f"payload {payload_key!r} uses unknown endpoint {endpoint!r} from {path.name}"
            )


def _validate_unmapped(path: Path, broker: str, origin: str, payloads: set[str]) -> set[str]:
    if not path.exists():
        return set()
    document = _mapping(_load_yaml(path), str(path))
    _allowed_keys(document, UNMAPPED_KEYS, str(path))
    for required in ("broker", "origin", "unmapped"):
        if required not in document:
            raise MappingSchemaError(f"{path}: missing required key {required!r}")
    if document["broker"] != broker:
        raise MappingSchemaError(f"{path}: broker does not match mappings.yaml")
    if document["origin"] != origin:
        raise MappingSchemaError(f"{path}: origin does not match mappings.yaml")
    if "notes" in document and not isinstance(document["notes"], str):
        raise MappingSchemaError(f"{path}: notes must be a string")
    entries = document["unmapped"]
    if not isinstance(entries, list):
        raise MappingSchemaError(f"{path}: unmapped must be a list")
    references: set[str] = set()
    for index, entry in enumerate(entries):
        where = f"{path}: unmapped[{index}]"
        if not isinstance(entry, dict) or len(entry) != 1:
            raise MappingSchemaError(f"{where} must be a one-entry mapping")
        reference, details = next(iter(entry.items()))
        _validate_raw_reference(reference, payloads, where)
        if reference in references:
            raise MappingSchemaError(f"{where} duplicates unmapped reference {reference!r}")
        references.add(reference)
        details = _mapping(details, f"{where} value")
        _allowed_keys(details, UNMAPPED_VALUE_KEYS, f"{where} value")
        if "reason" not in details:
            raise MappingSchemaError(f"{where} is missing required key 'reason'")
        _nonempty_string(details["reason"], f"{where} reason")
        for optional in ("note", "candidate_meaning"):
            if optional in details and not isinstance(details[optional], str):
                raise MappingSchemaError(f"{where} {optional} must be a string")
    return references


def validate_mapping_file(path: str | Path) -> None:
    """Validate one mappings.yaml and its sibling registry files, if present."""
    path = Path(path)
    document = _mapping(_load_yaml(path), str(path))
    _allowed_keys(document, MAPPING_KEYS, str(path))
    for required in ("broker", "origin", "payloads", "mappings"):
        if required not in document:
            raise MappingSchemaError(f"{path}: missing required key {required!r}")
    broker = _nonempty_string(document["broker"], f"{path}: broker")
    origin = _nonempty_string(document["origin"], f"{path}: origin")
    for optional in ("description", "notes"):
        if optional in document and not isinstance(document[optional], str):
            raise MappingSchemaError(f"{path}: {optional} must be a string")

    payload_definitions = _mapping(document["payloads"], f"{path}: payloads")
    if not payload_definitions:
        raise MappingSchemaError(f"{path}: payloads must not be empty")
    endpoints_used: list[tuple[str, str]] = []
    payloads: set[str] = set()
    for raw_key, raw_definition in payload_definitions.items():
        key = _validate_payload_key(raw_key, f"{path}: payload key")
        payloads.add(key)
        definition = _mapping(raw_definition, f"{path}: payload {key!r}")
        _allowed_keys(definition, PAYLOAD_KEYS, f"{path}: payload {key!r}")
        if "path" not in definition:
            raise MappingSchemaError(f"{path}: payload {key!r} is missing required key 'path'")
        _validate_payload_path(definition["path"], f"{path}: payload {key!r} path")
        endpoint = definition.get("endpoint", key)
        _nonempty_string(endpoint, f"{path}: payload {key!r} endpoint")
        if "description" in definition and not isinstance(definition["description"], str):
            raise MappingSchemaError(f"{path}: payload {key!r} description must be a string")
        if "row_filter" in definition:
            row_filter = _mapping(
                definition["row_filter"], f"{path}: payload {key!r} row_filter"
            )
            for filter_key, filter_value in row_filter.items():
                _nonempty_string(filter_key, f"{path}: payload {key!r} row_filter key")
                if not (filter_value is None or isinstance(filter_value, (str, int, float, bool))):
                    raise MappingSchemaError(
                        f"{path}: payload {key!r} row_filter values must be scalar"
                    )
        endpoints_used.append((key, endpoint))

    mappings = _mapping(document["mappings"], f"{path}: mappings")
    mapped_references: set[str] = set()
    for semantic_path, references in mappings.items():
        semantic_path = _nonempty_string(semantic_path, f"{path}: semantic path")
        if ("@" not in semantic_path or any(c.isspace() for c in semantic_path)
                or semantic_path in OLD_HELPER_KEYS):
            raise MappingSchemaError(f"{path}: invalid semantic path {semantic_path!r}")
        if not isinstance(references, list) or not references:
            raise MappingSchemaError(f"{path}: mapping {semantic_path!r} must be a non-empty list")
        for index, reference in enumerate(references):
            _validate_raw_reference(reference, payloads, f"{path}: {semantic_path}[{index}]")
            mapped_references.add(reference)

    transforms = document.get("transforms", {})
    transforms = _mapping(transforms, f"{path}: transforms")
    for semantic_path, raw_transforms in transforms.items():
        if semantic_path not in mappings:
            raise MappingSchemaError(
                f"{path}: transform semantic path {semantic_path!r} is not in mappings"
            )
        raw_transforms = _mapping(raw_transforms, f"{path}: transforms {semantic_path!r}")
        for raw_reference, raw_specification in raw_transforms.items():
            if raw_reference not in mappings[semantic_path]:
                raise MappingSchemaError(
                    f"{path}: transform raw reference {raw_reference!r} is not mapped under "
                    f"{semantic_path!r}"
                )
            specification = _mapping(
                raw_specification, f"{path}: transform {semantic_path!r} {raw_reference!r}"
            )
            _allowed_keys(
                specification, TRANSFORM_KEYS,
                f"{path}: transform {semantic_path!r} {raw_reference!r}",
            )
            transform_type = specification.get("type")
            if transform_type is not None and transform_type not in TRANSFORM_TYPES:
                raise MappingSchemaError(
                    f"{path}: transform type must be one of {sorted(TRANSFORM_TYPES)}"
                )
            if transform_type == "value_map" and "map" not in specification:
                raise MappingSchemaError(f"{path}: value_map transform requires 'map'")
            if "map" in specification and not isinstance(specification["map"], dict):
                raise MappingSchemaError(f"{path}: transform map must be a mapping")
            if "default" in specification and not (
                specification["default"] is None
                or isinstance(specification["default"], (str, int, float, bool))
            ):
                raise MappingSchemaError(f"{path}: transform default must be scalar or null")
            if "skip_null" in specification and not isinstance(
                specification["skip_null"], bool
            ):
                raise MappingSchemaError(f"{path}: transform skip_null must be boolean")
            if "note" in specification and not isinstance(specification["note"], str):
                raise MappingSchemaError(f"{path}: transform note must be a string")

    _validate_endpoints(path.with_name("endpoints.yaml"), endpoints_used)
    unmapped_references = _validate_unmapped(
        path.with_name("unmapped_fields.yaml"), broker, origin, payloads
    )
    overlap = mapped_references & unmapped_references
    if overlap:
        raise MappingSchemaError(
            f"{path}: references cannot be both mapped and unmapped: "
            f"{', '.join(sorted(overlap))}"
        )


def _is_legacy(path: Path) -> bool:
    document = _load_yaml(path)
    return not isinstance(document, dict) or "payloads" not in document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("path", nargs="?", type=Path)
    group.add_argument("--all", action="store_true", dest="validate_all")
    args = parser.parse_args(argv)
    paths = (sorted((Path(__file__).parents[1] / "providers").glob("*/*/mappings.yaml"))
             if args.validate_all else [args.path])
    failed = False
    for path in paths:
        try:
            if args.validate_all and _is_legacy(path):
                print(f"SKIPPED {path}: legacy schema without payloads")
                continue
            validate_mapping_file(path)
            print(f"PASSED {path}")
        except MappingSchemaError as exc:
            failed = True
            print(f"ERROR {path}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
