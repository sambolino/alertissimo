"""Build canonical semantic portfolios from physical endpoint executions."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import yaml

from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.execution import EndpointRegistry, ExecutionResult
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
from .intrinsic_array_collector import (
    IntrinsicArrayCollectionError,
    collect_intrinsic_array_records,
)
from .mapping_schema import validate_mapping_file
from .payload_paths import RawFieldMissing, extract_raw_field, resolve_payload_items


class PortfolioBuildError(ValueError):
    """Raised when a portfolio cannot be built from registry resources."""


_MISSING = object()


SEMANTIC_TYPE_PLACEHOLDER_DEFAULTS = {
    "producer": "unknown",
}

SEMANTIC_TYPE_BINDING_FIELD_PATHS = {
    "producer": ("provenance.producer.id", "provenance.producer.name"),
}

# Only labels that explicitly become semantic identifiers are normalized.
# Ordinary dynamic-container binders retain their endpoint-specific value.
SEMANTIC_IDENTIFIER_PLACEHOLDERS = frozenset({"producer", "output"})


def _semantic_identifier(value: Any) -> str:
    """Normalize a payload label for use in a semantic path segment."""
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")
    return normalized or "unknown"


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
        rewritten = []
        unresolved = False
        for segment in segments:
            name = _placeholder_name(segment)
            if name is not None and name not in bindings:
                unresolved = True
                break
            if name is None:
                rewritten.append(segment)
            elif name in SEMANTIC_IDENTIFIER_PLACEHOLDERS:
                rewritten.append(_semantic_identifier(bindings[name]))
            else:
                rewritten.append(str(bindings[name]))
        if unresolved:
            continue
        resolved[".".join(rewritten)] = value
    return resolved


def _resolve_dynamic_semantic_type(
    semantic_type: str,
    fields: Mapping[str, Any],
) -> str:
    """Resolve semantic-type placeholders from binders, stable fields, or defaults."""
    bindings, _ = _collect_dynamic_field_bindings(fields)

    def replacement(match: re.Match[str]) -> str:
        placeholder = match.group(1)
        if placeholder in bindings:
            return str(bindings[placeholder])
        for field_path in SEMANTIC_TYPE_BINDING_FIELD_PATHS.get(placeholder, ()):
            if field_path in fields:
                return _semantic_identifier(fields[field_path])
        return SEMANTIC_TYPE_PLACEHOLDER_DEFAULTS.get(placeholder, match.group(0))

    return _PLACEHOLDER_PATTERN.sub(replacement, semantic_type)


def new_internal_portfolio_id() -> InternalPortfolioId:
    return InternalPortfolioId(f"portfolio:{uuid4().hex}")


def new_internal_record_id() -> InternalRecordId:
    return InternalRecordId(f"record:{uuid4().hex}")


def _is_empty_mapping_value(value: Any) -> bool:
    """Return whether a value is an explicitly empty scalar/container payload."""

    return isinstance(
        value,
        (str, bytes, bytearray, list, tuple, dict, set, frozenset),
    ) and len(value) == 0


def _should_skip_mapping_value(
    value: Any, specification: Mapping[str, Any] | None
) -> bool:
    if not specification:
        return False
    if value is None and specification.get("skip_null", False):
        return True
    if specification.get("skip_empty", False) and _is_empty_mapping_value(value):
        return True
    return False


def _decode_serialized_array(value: Any) -> list[Any]:
    """Decode JSON- or brace-delimited array text into a structured list.

    Some upstream stores serialize arrays using JSON brackets while others emit
    brace-delimited array text. Non-finite ``NaN``/``Infinity`` elements are
    unavailable numeric features and normalize to ``None`` so downstream JSON
    remains standards-compliant.
    """

    if isinstance(value, (list, tuple)):
        return list(value)
    if not isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"cannot decode serialized array from {value!r}")
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8")
    text = value.strip()
    if text.startswith("{") and text.endswith("}"):
        text = f"[{text[1:-1]}]"
    try:
        decoded = json.loads(text, parse_constant=lambda _: None)
    except json.JSONDecodeError as error:
        raise ValueError(f"cannot decode serialized array {value!r}") from error
    if not isinstance(decoded, list):
        raise ValueError(f"serialized array did not decode to a list: {value!r}")
    return decoded


def _apply_transform(value: Any, specification: Mapping[str, Any] | None) -> Any:
    if not specification:
        return value
    transform_type = specification.get("type")
    if transform_type is None:
        return value
    if transform_type == "boolean_not":
        return not bool(value)
    if transform_type == "value_map":
        fallback = specification.get("default", value)
        return specification["map"].get(value, fallback)
    if transform_type == "jd_to_mjd":
        return value - 2400000.5
    if value is None:
        return None
    if transform_type == "array_decode":
        return _decode_serialized_array(value)
    if transform_type == "scale":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"cannot scale non-numeric value {value!r}")
        return value * specification["factor"]
    if transform_type == "to_string_strip":
        return str(value).strip()
    if transform_type == "to_float":
        try:
            return float(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"cannot convert {value!r} to float") from error
    if transform_type == "to_int":
        if isinstance(value, int):
            return int(value)
        try:
            converted = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise ValueError(f"cannot convert {value!r} to int") from error
        if not converted.is_finite() or converted != converted.to_integral_value():
            raise ValueError(f"cannot convert non-integral value {value!r} to int")
        return int(converted)
    return value  # The mapping schema rejects unknown transform types.


def _bound_target_ids(
    execution: ExecutionResult,
    *,
    providers_root: Path,
) -> tuple[Any, ...]:
    """Recover target identities declared by the physical request contract."""

    provenance = execution.execution_provenance
    try:
        spec = EndpointRegistry(providers_root).resolve(
            provenance.broker,
            provenance.origin,
            provenance.endpoint,
        )
    except (FileNotFoundError, KeyError):
        # Mapping-only fixtures and custom registries are valid normalization inputs.
        # Without an endpoint contract there is simply no request-binding evidence
        # from which to synthesize semantic object identity.
        return ()

    values: list[Any] = []
    for physical_name, declaration in spec.params.items():
        if not isinstance(declaration, Mapping) or declaration.get("bind") != "target_id":
            continue
        if physical_name not in provenance.params:
            continue
        raw_value = provenance.params[physical_name]
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
            if candidate not in values:
                values.append(candidate)
    return tuple(values)


def _complete_minimal_summary_identity(
    records_by_object: dict[Any, list[SemanticRecord]],
    *,
    broker: str,
    origin: str,
    request_target_ids: tuple[Any, ...],
    make_record_id: Callable[[], InternalRecordId],
) -> None:
    """Seed an id-only summary for one unambiguous target-bound object retrieval.

    When one requested object yields only detections, lightcurve points, or other
    enrichment records, the requested target ID is sufficient semantic evidence for
    the Portfolio identity. Search-result partition keys are not promoted into
    summaries, and multi-target calls are not correlated by position or guesswork.
    """

    if len(request_target_ids) != 1 or len(records_by_object) != 1:
        return
    records = next(iter(records_by_object.values()))
    if any(
        record.semantic_type.split("@", 1)[0] == "summary"
        and record.get("identity.object_id") is not None
        for record in records
    ):
        return
    records.append(
        SemanticRecord(
            internal_record_id=make_record_id(),
            semantic_type=f"summary@{origin}:{broker}",
            fields={"identity.object_id": request_target_ids[0]},
            internal_source=None,
        )
    )


def build_portfolios_from_execution(
    execution: ExecutionResult,
    *,
    mappings_path: Path | None = None,
    providers_root: Path | None = None,
    internal_portfolio_id: InternalPortfolioId | None = None,
    record_id_factory: Callable[[], InternalRecordId] | None = None,
    validate_semantic_model: bool = False,
    semantic_model: SemanticModelIndex | None = None,
) -> tuple[Portfolio, ...]:
    """Normalize one physical execution into execution-local object Portfolios."""
    root = Path(providers_root) if providers_root is not None else PROVIDERS_ROOT
    mappings_from_registry = mappings_path is None
    if mappings_from_registry:
        provenance = execution.execution_provenance
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
    records_by_object: dict[Any, list[SemanticRecord]] = {}
    make_record_id = record_id_factory or new_internal_record_id

    # Search endpoints may return one-shot iterators. Materialize once so all
    # payload definitions in this build see the identical finite result set.
    payload = execution.payload
    if isinstance(payload, Iterator):
        payload = tuple(payload)

    for payload_key, payload_definition in payload_definitions.items():
        endpoint = payload_definition.get("endpoint", payload_key)
        if endpoint != execution.execution_provenance.endpoint:
            continue
        payload_path = payload_definition["path"]
        partition = payload_definition.get("object_partition")
        # Unmapped payload definitions are deliberately harmless.
        if partition is None:
            continue
        # A mapped non-object payload remains part of semantic registry
        # validation, but cannot create an astronomical-object Portfolio.
        if partition["mode"] == "none":
            continue
        items = resolve_payload_items(
            payload,
            payload_key=payload_key,
            payload_path=payload_path,
        )
        for item in items:
            mode = partition["mode"]
            if mode == "single":
                partition_key: Any = ("single",)
            else:
                source = item.value if mode == "field" else item.root_value
                try:
                    partition_value = extract_raw_field(source, partition["field"])
                except RawFieldMissing as error:
                    raise PortfolioBuildError(
                        f"payload {payload_key!r} object partition field "
                        f"{partition['field']!r} is missing"
                    ) from error
                if partition_value is None or isinstance(partition_value, bool):
                    raise PortfolioBuildError(
                        f"payload {payload_key!r} has unusable object partition "
                        f"value {partition_value!r}"
                    )
                try:
                    hash(partition_value)
                except TypeError as error:
                    raise PortfolioBuildError(
                        f"payload {payload_key!r} has unhashable object partition value"
                    ) from error
                # Field and root-field declarations intentionally share identity.
                partition_key = ("identity", partition_value)
            fields_by_type: dict[str, dict[str, Any]] = {}
            for semantic_path, references in mappings.items():
                semantic_type, relative_field = split_semantic_path(semantic_path)
                ordinary_value: Any = _MISSING
                composed_entries: dict[str, Any] = {}
                for raw_reference in references:
                    ref_payload_key, raw_field = raw_reference.split("#", 1)
                    if ref_payload_key != payload_key:
                        continue
                    specification = transforms.get(semantic_path, {}).get(raw_reference)
                    object_key = specification.get("object_key") if specification else None
                    # Once an ordinary fallback succeeds, only composition
                    # references still need evaluation for conflict detection.
                    if object_key is None and ordinary_value is not _MISSING:
                        continue
                    try:
                        value = extract_raw_field(item.value, raw_field)
                    except RawFieldMissing:
                        continue
                    # Skip explicit null/empty sentinels both before and after
                    # transforms. The second check handles transforms that turn
                    # a serialized value into an empty structured value.
                    if _should_skip_mapping_value(value, specification):
                        continue
                    value = _apply_transform(value, specification)
                    if _should_skip_mapping_value(value, specification):
                        continue
                    if object_key is not None:
                        if object_key in composed_entries and composed_entries[object_key] != value:
                            raise PortfolioBuildError(
                                f"conflicting values for object key {object_key!r} in "
                                f"{semantic_type}.{relative_field}: "
                                f"{composed_entries[object_key]!r} vs {value!r}"
                            )
                        composed_entries[object_key] = value
                        continue
                    ordinary_value = value

                if ordinary_value is not _MISSING and composed_entries:
                    raise PortfolioBuildError(
                        f"mixed ordinary assignment and object composition for "
                        f"{semantic_type}.{relative_field}"
                    )
                if composed_entries:
                    fields_by_type.setdefault(semantic_type, {})[relative_field] = composed_entries
                elif ordinary_value is not _MISSING:
                    fields_by_type.setdefault(semantic_type, {})[relative_field] = ordinary_value

            for semantic_type, fields in fields_by_type.items():
                if not fields:
                    continue
                semantic_type = _resolve_dynamic_semantic_type(semantic_type, fields)
                fields = _resolve_dynamic_field_paths(fields)
                if not fields:
                    continue
                records_by_object.setdefault(partition_key, []).append(
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

    try:
        records_by_object = {
            partition_key: list(collect_intrinsic_array_records(records))
            for partition_key, records in records_by_object.items()
        }
    except IntrinsicArrayCollectionError as error:
        raise PortfolioBuildError(
            f"cannot collect intrinsic semantic arrays: {error}"
        ) from error

    request_target_ids = (
        _bound_target_ids(execution, providers_root=root)
        if mappings_from_registry
        else ()
    )
    _complete_minimal_summary_identity(
        records_by_object,
        broker=document.get("broker", execution.execution_provenance.broker),
        origin=document.get("origin", execution.execution_provenance.origin),
        request_target_ids=request_target_ids,
        make_record_id=make_record_id,
    )

    if internal_portfolio_id is not None and len(records_by_object) != 1:
        raise PortfolioBuildError(
            "internal_portfolio_id requires exactly one normalized object; "
            f"found {len(records_by_object)}"
        )
    portfolios = tuple(
        Portfolio(
            internal_portfolio_id=internal_portfolio_id or new_internal_portfolio_id(),
            records=tuple(records),
            edges=(),
            executions=(execution.execution_provenance,),
        )
        for records in records_by_object.values()
    )
    if validate_semantic_model:
        for portfolio in portfolios:
            validate_portfolio_against_semantic_model(portfolio, semantic_model)
    return portfolios


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
    """Strict compatibility API for endpoints known to return one object."""
    portfolios = build_portfolios_from_execution(
        execution,
        mappings_path=mappings_path,
        providers_root=providers_root,
        internal_portfolio_id=internal_portfolio_id,
        record_id_factory=record_id_factory,
        validate_semantic_model=validate_semantic_model,
        semantic_model=semantic_model,
    )
    if len(portfolios) != 1:
        raise PortfolioBuildError(
            "singular portfolio builder requires exactly one normalized object; "
            f"found {len(portfolios)}"
        )
    return portfolios[0]