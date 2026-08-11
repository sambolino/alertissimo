"""Build canonical semantic portfolios from physical endpoint executions."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import yaml

from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import (
    InternalPortfolioId,
    InternalRecordId,
    InternalRecordSource,
    Portfolio,
    SemanticRecord,
)
from alertissimo.data_layer.semantic_model.index import SemanticModelIndex
from alertissimo.data_layer.semantic_model.validation import (
    validate_portfolio_against_semantic_model,
)

from .capability_graph import split_semantic_path
from .mapping_schema import validate_mapping_file
from .payload_paths import RawFieldMissing, extract_raw_field, resolve_payload_items


class PortfolioBuildError(ValueError):
    """Raised when a portfolio cannot be built from registry resources."""


SEMANTIC_TYPE_PLACEHOLDER_DEFAULTS = {
    "producer": "unknown",
}

_PLACEHOLDER_PATTERN = re.compile(r"\{([^{}]+)\}")


def _placeholder_name(segment: str) -> str | None:
    """Return the name of a placeholder that occupies an entire path segment."""
    if len(segment) >= 3 and segment.startswith("{") and segment.endswith("}"):
        name = segment[1:-1]
        if name and "{" not in name and "}" not in name:
            return name
    return None


def _collect_dynamic_field_bindings(
    fields: Mapping[str, Any],
) -> tuple[dict[str, Any], set[str]]:
    """Collect values supplied by final-segment placeholder fields."""
    bindings: dict[str, Any] = {}
    binder_paths: set[str] = set()
    for path, value in fields.items():
        placeholder = _placeholder_name(path.split(".")[-1])
        if placeholder is None:
            continue
        if placeholder in bindings and bindings[placeholder] != value:
            previous = bindings[placeholder]
            raise PortfolioBuildError(
                f"conflicting binding for placeholder {{{placeholder}}}: "
                f"{previous} vs {value}"
            )
        bindings[placeholder] = value
        binder_paths.add(path)
    return bindings, binder_paths


def _resolve_dynamic_field_paths(fields: dict[str, Any]) -> dict[str, Any]:
    """Bind final-segment placeholders and rewrite sibling relative paths."""
    bindings, binder_paths = _collect_dynamic_field_bindings(fields)

    resolved: dict[str, Any] = {}
    for path, value in fields.items():
        if path in binder_paths:
            continue
        segments = path.split(".")
        rewritten = [
            str(bindings[name])
            if (name := _placeholder_name(segment)) in bindings
            else segment
            for segment in segments
        ]
        resolved[".".join(rewritten)] = value
    return resolved


def _resolve_dynamic_semantic_type(
    semantic_type: str,
    fields: Mapping[str, Any],
) -> str:
    """Resolve semantic-type placeholders, applying only explicit defaults."""
    bindings, _ = _collect_dynamic_field_bindings(fields)

    def replacement(match: re.Match[str]) -> str:
        placeholder = match.group(1)
        if placeholder in bindings:
            return str(bindings[placeholder])
        return SEMANTIC_TYPE_PLACEHOLDER_DEFAULTS.get(placeholder, match.group(0))

    return _PLACEHOLDER_PATTERN.sub(replacement, semantic_type)


def new_internal_portfolio_id() -> InternalPortfolioId:
    return InternalPortfolioId(f"portfolio:{uuid4().hex}")


def new_internal_record_id() -> InternalRecordId:
    return InternalRecordId(f"record:{uuid4().hex}")


def _apply_transform(value: Any, specification: Mapping[str, Any] | None) -> Any:
    if not specification:
        return value
    transform_type = specification["type"]
    if transform_type == "boolean_not":
        return not bool(value)
    if transform_type == "value_map":
        fallback = specification.get("default", value)
        return specification["map"].get(value, fallback)
    if transform_type == "to_string_strip":
        return None if value is None else str(value).strip()
    if transform_type == "to_float":
        return None if value is None else float(value)
    if transform_type == "jd_to_mjd":
        return value - 2400000.5
    return value  # The mapping schema rejects unknown transform types.


def build_portfolio_from_execution(
    execution: ExecutionResult,
    *,
    mappings_path: Path | None = None,
    providers_root: Path | None = None,
    internal_portfolio_id: InternalPortfolioId | None = None,
    record_id_factory: Callable[[], InternalRecordId] | None = None,
    validate_semantic_model: bool = False,
    semantic_model: SemanticModelIndex | None = None,
) -> Portfolio:
    """Interpret one provider mapping and transform an execution's raw payload."""
    if mappings_path is None:
        provenance = execution.execution_provenance
        root = Path(providers_root) if providers_root is not None else PROVIDERS_ROOT
        mappings_path = root / provenance.broker / provenance.origin / "mappings.yaml"
        if not mappings_path.is_file():
            raise PortfolioBuildError(
                f"cannot resolve mappings.yaml for {provenance.broker}/"
                f"{provenance.origin} under {root}"
            )
    else:
        mappings_path = Path(mappings_path)

    try:
        validate_mapping_file(mappings_path)
        with mappings_path.open(encoding="utf-8") as stream:
            document = yaml.safe_load(stream)
    except (OSError, yaml.YAMLError) as error:
        raise PortfolioBuildError(
            f"cannot load portfolio mappings from {mappings_path}: {error}"
        ) from error

    payload_definitions = document["payloads"]
    mappings = document["mappings"]
    transforms = document.get("transforms", {})
    records: list[SemanticRecord] = []
    make_record_id = record_id_factory or new_internal_record_id

    for payload_key, payload_definition in payload_definitions.items():
        if (payload_definition.get("endpoint") is not None
                and payload_definition["endpoint"] != execution.execution_provenance.endpoint):
            continue
        payload_path = payload_definition["path"]
        items = resolve_payload_items(
            execution.payload,
            payload_key=payload_key,
            payload_path=payload_path,
        )
        for item in items:
            fields_by_type: dict[str, dict[str, Any]] = {}
            for semantic_path, references in mappings.items():
                semantic_type, relative_field = split_semantic_path(semantic_path)
                for raw_reference in references:
                    ref_payload_key, raw_field = raw_reference.split("#", 1)
                    if ref_payload_key != payload_key:
                        continue
                    try:
                        value = extract_raw_field(item.value, raw_field)
                    except RawFieldMissing:
                        continue
                    specification = transforms.get(semantic_path, {}).get(raw_reference)
                    fields_by_type.setdefault(semantic_type, {})[relative_field] = (
                        _apply_transform(value, specification)
                    )
                    break

            for semantic_type, fields in fields_by_type.items():
                if not fields:
                    continue
                semantic_type = _resolve_dynamic_semantic_type(semantic_type, fields)
                fields = _resolve_dynamic_field_paths(fields)
                if not fields:
                    continue
                records.append(
                    SemanticRecord(
                        internal_record_id=make_record_id(),
                        semantic_type=semantic_type,
                        fields=fields,
                        internal_source=InternalRecordSource(
                            internal_execution_id=execution.internal_execution_id,
                            payload_key=payload_key,
                            payload_path=payload_path,
                            payload_index=item.payload_index,
                        ),
                    )
                )

    portfolio = Portfolio(
        internal_portfolio_id=internal_portfolio_id or new_internal_portfolio_id(),
        records=tuple(records),
        edges=(),
        executions=(execution.execution_provenance,),
    )
    if validate_semantic_model:
        validate_portfolio_against_semantic_model(portfolio, semantic_model)
    return portfolio
