"""Resolve the deliberately small payload path notation used by mappings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ResolvedPayloadItem:
    payload_key: str
    payload_path: str
    value: Any
    payload_index: int | None = None
    index_path: tuple[int, ...] = ()
    root_value: Any = None


class RawFieldMissing(LookupError):
    """Raised internally when a raw field is absent or cannot be traversed."""


def _mapping_path(value: Any, path: str) -> Any:
    current = value
    for key in path.split("."):
        if isinstance(current, Mapping) and key in current:
            current = current[key]
            continue
        if isinstance(current, (list, tuple)) and key.isdigit():
            index = int(key)
            if index < len(current):
                current = current[index]
                continue
        # Provider client models commonly expose payload data as attributes.
        # Resolve only the explicitly requested public name, and never call it.
        if key and not key.startswith("_"):
            try:
                candidate = getattr(current, key)
            except AttributeError:
                pass
            else:
                if not callable(candidate):
                    current = candidate
                    continue
        if not key:
            raise RawFieldMissing(path)
        raise RawFieldMissing(path)
    return current


def resolve_payload_items(
    payload: Any,
    *,
    payload_key: str,
    payload_path: str,
) -> tuple[ResolvedPayloadItem, ...]:
    """Resolve a mapping payload path without implementing general JSONPath."""
    if payload_path == ".":
        return (
            ResolvedPayloadItem(
                payload_key, payload_path, payload, root_value=payload
            ),
        )

    root_expansion = payload_path.startswith("[].")
    path = payload_path[3:] if root_expansion else payload_path
    expansion = path[-2:] if path.endswith(("[]", "{}")) else ""
    collection_path = path[:-2] if expansion else path
    if (
        not expansion
        or not collection_path
        or "[]" in collection_path
        or "{}" in collection_path
        or any(
            not part or not part.replace("_", "a").isalnum()
            for part in collection_path.split(".")
        )
    ):
        if payload_path == "[]":
            root_expansion = True
            path = ""
            expansion = "[]"
        else:
            raise ValueError(f"invalid payload path: {payload_path!r}")

    roots: tuple[tuple[Any, tuple[int, ...]], ...]
    if root_expansion:
        if not isinstance(payload, (list, tuple)):
            return ()
        roots = tuple((value, (index,)) for index, value in enumerate(payload))
    else:
        roots = ((payload, ()),)

    resolved: list[tuple[Any, tuple[int, ...]]] = []
    for root, root_indexes in roots:
        if not path:  # root list, "[]"
            resolved.append((root, root_indexes))
            continue
        try:
            collection = _mapping_path(root, collection_path)
        except RawFieldMissing:
            continue
        if expansion == "[]":
            if not isinstance(collection, (list, tuple)):
                continue
            values = collection
        else:
            if not isinstance(collection, Mapping):
                continue
            values = tuple(
                {"_key": key, "_value": value}
                for key, value in sorted(collection.items(), key=lambda item: str(item[0]))
            )
        resolved.extend(
            (value, (*root_indexes, index)) for index, value in enumerate(values)
        )

    return tuple(
        ResolvedPayloadItem(
            payload_key=payload_key,
            payload_path=payload_path,
            value=value,
            payload_index=index,
            index_path=index_path,
            root_value=(
                payload[index_path[0]]
                if root_expansion and index_path
                else payload
            ),
        )
        for index, (value, index_path) in enumerate(resolved)
    )


def extract_raw_field(value: Any, field_path: str) -> Any:
    """Extract a dot-separated field, raising ``RawFieldMissing`` if absent."""
    if not isinstance(field_path, str) or not field_path or any(
        not part for part in field_path.split(".")
    ):
        raise ValueError(f"invalid raw field path: {field_path!r}")
    return _mapping_path(value, field_path)
