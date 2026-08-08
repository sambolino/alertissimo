"""Parser and validator for the human-authored minimal mapping schema."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml


ALLOWED_PAYLOAD_KEYS = frozenset({"path", "endpoint", "description"})
FORBIDDEN_MAPPING_KEYS = frozenset(
    {
        "endpoints",
        "availability",
        "field_status",
        "source_fields",
        "record_type",
        "object_summary",
    }
)


class MappingSchemaError(ValueError):
    """Raised when a registry file does not use the minimal mapping schema."""


def _read_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def _require_nonempty_string(data: Mapping[str, Any], key: str, source: str) -> None:
    if not isinstance(data.get(key), str) or not data[key].strip():
        raise MappingSchemaError(f"{source}: {key!r} must be a non-empty string")


def _payload_from_reference(reference: Any, source: str) -> str:
    if not isinstance(reference, str) or reference.count("#") != 1:
        raise MappingSchemaError(
            f"{source}: raw reference must have the form '<payload>#<raw_field>'"
        )
    payload, raw_field = reference.split("#")
    if not payload or not raw_field:
        raise MappingSchemaError(
            f"{source}: raw reference must have the form '<payload>#<raw_field>'"
        )
    return payload


def _endpoint_names(data: Any, source: str) -> set[str]:
    if not isinstance(data, Mapping) or not isinstance(data.get("endpoints"), Mapping):
        raise MappingSchemaError(f"{source}: 'endpoints' must be a mapping")
    return set(data["endpoints"])


def validate_mapping_data(
    data: Any, *, endpoints: Any | None = None, source: str = "mappings.yaml"
) -> dict[str, Any]:
    """Validate parsed mapping data and return it unchanged.

    ``endpoints`` is parsed endpoints.yaml data.  When supplied, both explicit
    payload endpoints and implicit (payload-key) endpoints must be declared.
    """
    if not isinstance(data, dict):
        raise MappingSchemaError(f"{source}: document must be a mapping")
    _require_nonempty_string(data, "broker", source)
    _require_nonempty_string(data, "origin", source)

    payloads = data.get("payloads")
    if not isinstance(payloads, dict) or not payloads:
        raise MappingSchemaError(f"{source}: 'payloads' must be a non-empty mapping")

    known_endpoints = _endpoint_names(endpoints, "endpoints.yaml") if endpoints is not None else None
    for payload_key, payload in payloads.items():
        if not isinstance(payload_key, str) or not payload_key:
            raise MappingSchemaError(f"{source}: payload keys must be non-empty strings")
        if not isinstance(payload, dict):
            raise MappingSchemaError(f"{source}: payload {payload_key!r} must be a mapping")
        forbidden = set(payload) & FORBIDDEN_MAPPING_KEYS
        unknown = set(payload) - ALLOWED_PAYLOAD_KEYS
        if forbidden:
            raise MappingSchemaError(
                f"{source}: payload {payload_key!r} contains forbidden keys: {sorted(forbidden)}"
            )
        if unknown:
            raise MappingSchemaError(
                f"{source}: payload {payload_key!r} contains unsupported keys: {sorted(unknown)}"
            )
        _require_nonempty_string(payload, "path", f"{source}: payload {payload_key!r}")
        endpoint = payload.get("endpoint", payload_key)
        if not isinstance(endpoint, str) or not endpoint:
            raise MappingSchemaError(f"{source}: payload {payload_key!r} has an invalid endpoint")
        if known_endpoints is not None and endpoint not in known_endpoints:
            raise MappingSchemaError(
                f"{source}: payload {payload_key!r} references unknown endpoint {endpoint!r}"
            )

    mappings = data.get("mappings")
    if not isinstance(mappings, dict):
        raise MappingSchemaError(f"{source}: 'mappings' must be a mapping")
    for feature_id, references in mappings.items():
        if not isinstance(references, list):
            if isinstance(references, dict):
                forbidden = set(references) & FORBIDDEN_MAPPING_KEYS
                if forbidden:
                    raise MappingSchemaError(
                        f"{source}: mapping {feature_id!r} contains forbidden keys: {sorted(forbidden)}"
                    )
            raise MappingSchemaError(f"{source}: mapping {feature_id!r} must be a list of raw references")
        for reference in references:
            payload_key = _payload_from_reference(reference, f"{source}: mapping {feature_id!r}")
            if payload_key not in payloads:
                raise MappingSchemaError(
                    f"{source}: raw reference {reference!r} uses unknown payload {payload_key!r}"
                )
    return data


def validate_unmapped_data(
    data: Any, *, payloads: Mapping[str, Any], source: str = "unmapped_fields.yaml"
) -> dict[str, Any]:
    """Validate unmapped raw references against the mapping payload vocabulary."""
    if not isinstance(data, dict):
        raise MappingSchemaError(f"{source}: document must be a mapping")
    _require_nonempty_string(data, "broker", source)
    _require_nonempty_string(data, "origin", source)
    entries = data.get("unmapped")
    if not isinstance(entries, list):
        raise MappingSchemaError(f"{source}: 'unmapped' must be a list")
    for entry in entries:
        if not isinstance(entry, dict) or len(entry) != 1:
            raise MappingSchemaError(f"{source}: each unmapped item must contain one raw reference")
        reference = next(iter(entry))
        payload_key = _payload_from_reference(reference, source)
        if payload_key not in payloads:
            raise MappingSchemaError(
                f"{source}: raw reference {reference!r} uses unknown payload {payload_key!r}"
            )
    return data


def load_mapping_registry(
    mappings_path: str | Path,
    *,
    endpoints_path: str | Path | None = None,
    unmapped_fields_path: str | Path | None = None,
) -> dict[str, Any]:
    """Load and validate mappings plus available sibling registry documents."""
    mappings_file = Path(mappings_path)
    sibling_endpoints = mappings_file.with_name("endpoints.yaml")
    endpoint_file = Path(endpoints_path) if endpoints_path is not None else sibling_endpoints
    endpoints = _read_yaml(endpoint_file) if endpoint_file.is_file() else None

    data = validate_mapping_data(_read_yaml(mappings_file), endpoints=endpoints, source=str(mappings_file))

    sibling_unmapped = mappings_file.with_name("unmapped_fields.yaml")
    unmapped_file = Path(unmapped_fields_path) if unmapped_fields_path is not None else sibling_unmapped
    if unmapped_file.is_file():
        unmapped = validate_unmapped_data(
            _read_yaml(unmapped_file), payloads=data["payloads"], source=str(unmapped_file)
        )
        if unmapped["broker"] != data["broker"] or unmapped["origin"] != data["origin"]:
            raise MappingSchemaError(
                f"{unmapped_file}: broker and origin must match {mappings_file}"
            )
    return data
