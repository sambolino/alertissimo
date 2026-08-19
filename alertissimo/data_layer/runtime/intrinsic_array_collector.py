"""Collect row-wise semantic fragments into intrinsic array-valued records.

The provider mapping layer is intentionally row-oriented: one selected payload row
can emit one semantic fragment. Some ontology fields, however, are intrinsically
array-valued (currently the point collections on ``lightcurve``). This module
collapses those row fragments after mapping without adding collection directives
to provider registries.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from alertissimo.data_layer.representations import (
    InternalRecordSource,
    SemanticRecord,
)


class IntrinsicArrayCollectionError(ValueError):
    """Raised when row fragments cannot be safely collected."""


# These are ontology-owned intrinsic arrays. Provider mappings address fields
# below them (for example ``points.time.mjd``); the collector turns those flat
# row fragments into ``fields["points"] == ({...}, ...)``.
_INTRINSIC_ARRAY_FIELDS = {
    "lightcurve": frozenset(
        {
            "points",
            "forced_photometry_points",
            "magnitude_rate_points",
            "color_points",
            "feature_vector_points",
        }
    ),
}

# All current intrinsic lightcurve arrays are point-like and inherit this shared
# context from ``_time_series_point``. Context alone must not materialize a point:
# an item needs at least one family-specific datum such as photometry, a rate,
# color, forced photometry, or a feature-vector value.
_POINT_CONTEXT_ROOTS = frozenset({"time", "quality", "identity", "provenance"})


def _base_semantic_type(semantic_type: str) -> str:
    return semantic_type.split("@", 1)[0]


def _array_fields_for(semantic_type: str) -> frozenset[str]:
    return _INTRINSIC_ARRAY_FIELDS.get(_base_semantic_type(semantic_type), frozenset())


def _record_has_intrinsic_array_fragment(record: SemanticRecord) -> bool:
    array_fields = _array_fields_for(record.semantic_type)
    if not array_fields:
        return False
    for field_path in record.fields:
        head = field_path.split(".", 1)[0]
        if head in array_fields:
            return True
    return False


def _item_has_substantive_fields(item: Mapping[str, Any]) -> bool:
    """Return whether a point item carries more than shared point context."""

    return any(
        field_path.split(".", 1)[0] not in _POINT_CONTEXT_ROOTS
        for field_path in item
    )


def _copy_array_items(
    value: Any, *, semantic_type: str, field_name: str
) -> list[dict[str, Any]]:
    if not isinstance(value, (tuple, list)):
        raise IntrinsicArrayCollectionError(
            f"{semantic_type}.{field_name} must be an array value during collection"
        )
    items: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise IntrinsicArrayCollectionError(
                f"{semantic_type}.{field_name}[{index}] must be a mapping"
            )
        copied = dict(item)
        if _item_has_substantive_fields(copied):
            items.append(copied)
    return items


def _split_fragment_fields(
    record: SemanticRecord,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """Split one record into root fields and zero-or-more intrinsic array items."""

    array_fields = _array_fields_for(record.semantic_type)
    root_fields: dict[str, Any] = {}
    existing_arrays: dict[str, list[dict[str, Any]]] = {}
    flat_items: dict[str, dict[str, Any]] = {}

    for field_path, value in record.fields.items():
        if field_path in array_fields:
            existing_arrays.setdefault(field_path, []).extend(
                _copy_array_items(
                    value,
                    semantic_type=record.semantic_type,
                    field_name=field_path,
                )
            )
            continue

        head, separator, tail = field_path.partition(".")
        if separator and head in array_fields:
            if head in existing_arrays:
                raise IntrinsicArrayCollectionError(
                    f"{record.semantic_type} mixes materialized {head!r} with flat {head}.* fields"
                )
            point = flat_items.setdefault(head, {})
            if tail in point and point[tail] != value:
                raise IntrinsicArrayCollectionError(
                    f"conflicting values for {record.semantic_type}.{head}.{tail}"
                )
            point[tail] = value
            continue

        root_fields[field_path] = value

    arrays = dict(existing_arrays)
    for field_name, point in flat_items.items():
        if point and _item_has_substantive_fields(point):
            arrays.setdefault(field_name, []).append(point)
    return root_fields, arrays


def _merge_root_field(
    fields: dict[str, Any],
    *,
    semantic_type: str,
    field_path: str,
    value: Any,
) -> None:
    if field_path not in fields:
        fields[field_path] = value
        return
    if fields[field_path] != value:
        raise IntrinsicArrayCollectionError(
            f"conflicting root values while collecting {semantic_type}.{field_path}: "
            f"{fields[field_path]!r} vs {value!r}"
        )


def _collection_source(records: Sequence[SemanticRecord]) -> InternalRecordSource | None:
    """Return an honest collection-level source when all fragments share a surface."""

    sources = [record.internal_source for record in records]
    if not sources or any(source is None for source in sources):
        return None
    concrete = [source for source in sources if source is not None]
    first = concrete[0]
    if any(
        source.internal_execution_id != first.internal_execution_id
        or source.payload_key != first.payload_key
        or source.payload_path != first.payload_path
        for source in concrete[1:]
    ):
        return None
    if all(source == first for source in concrete[1:]):
        return first
    return InternalRecordSource(
        internal_execution_id=first.internal_execution_id,
        payload_key=first.payload_key,
        payload_path=first.payload_path,
        payload_index=None,
    )


def _collect_group(records: Sequence[SemanticRecord]) -> SemanticRecord | None:
    first = records[0]
    root_fields: dict[str, Any] = {}
    arrays: dict[str, list[dict[str, Any]]] = {}

    for record in records:
        fragment_root, fragment_arrays = _split_fragment_fields(record)
        for field_path, value in fragment_root.items():
            _merge_root_field(
                root_fields,
                semantic_type=first.semantic_type,
                field_path=field_path,
                value=value,
            )
        for field_name, items in fragment_arrays.items():
            arrays.setdefault(field_name, []).extend(items)

    fields = dict(root_fields)
    for field_name, items in arrays.items():
        if items:
            fields[field_name] = tuple(items)

    if not fields:
        return None

    return SemanticRecord(
        internal_record_id=first.internal_record_id,
        semantic_type=first.semantic_type,
        fields=fields,
        internal_source=_collection_source(records),
    )


def collect_intrinsic_array_records(
    records: Sequence[SemanticRecord],
) -> tuple[SemanticRecord, ...]:
    """Collapse row fragments for semantic types carrying intrinsic array fields.

    Collection is deterministic and stable: a collected record occupies the
    position of the first fragment of its semantic type, point order follows
    payload-fragment order, and unrelated semantic records are untouched.
    """

    collectable_types = {
        record.semantic_type
        for record in records
        if _record_has_intrinsic_array_fragment(record)
    }
    if not collectable_types:
        return tuple(records)

    groups = {
        semantic_type: [
            record for record in records if record.semantic_type == semantic_type
        ]
        for semantic_type in collectable_types
    }
    collected = {
        semantic_type: _collect_group(group)
        for semantic_type, group in groups.items()
    }

    emitted: set[str] = set()
    result: list[SemanticRecord] = []
    for record in records:
        semantic_type = record.semantic_type
        if semantic_type not in collectable_types:
            result.append(record)
            continue
        if semantic_type in emitted:
            continue
        collected_record = collected[semantic_type]
        if collected_record is not None:
            result.append(collected_record)
        emitted.add(semantic_type)
    return tuple(result)


__all__ = [
    "IntrinsicArrayCollectionError",
    "collect_intrinsic_array_records",
]
