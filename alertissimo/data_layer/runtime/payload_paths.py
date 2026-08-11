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


class RawFieldMissing(LookupError):
    """Raised internally when a raw field is absent or cannot be traversed."""


def _mapping_path(value: Any, path: str) -> Any:
    current = value
    for key in path.split("."):
        if not key:
            raise RawFieldMissing(path)
        if isinstance(current, Mapping) and key in current:
            current = current[key]
        elif isinstance(current, (list, tuple)) and key.isdigit():
            try:
                current = current[int(key)]
            except IndexError as exc:
                raise RawFieldMissing(path) from exc
        else:
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
        return (ResolvedPayloadItem(payload_key, payload_path, payload),)

    dictionary_expansion = payload_path.endswith("{}")
    root_expansion = payload_path.startswith("[].")
    path = payload_path[3:] if root_expansion else payload_path
    collection_suffix = "{}" if dictionary_expansion else "[]"
    if (
        not path.endswith(collection_suffix)
        or path == "[]"
        or "[]" in path[:-2]
        or "{}" in path[:-2]
        or any(not part or not part.replace("_", "a").isalnum() for part in path[:-2].split("."))
    ):
        if payload_path == "[]":
            root_expansion = True
            path = ""
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
            collection = _mapping_path(root, path[:-2])
        except RawFieldMissing:
            continue
        if dictionary_expansion:
            if not isinstance(collection, Mapping):
                continue
            resolved.extend(
                ({"_key": key, "_value": value}, (*root_indexes, index))
                for index, (key, value) in enumerate(collection.items())
            )
        else:
            if not isinstance(collection, (list, tuple)):
                continue
            resolved.extend(
                (value, (*root_indexes, index))
                for index, value in enumerate(collection)
            )

    return tuple(
        ResolvedPayloadItem(
            payload_key=payload_key,
            payload_path=payload_path,
            value=value,
            payload_index=index,
            index_path=index_path,
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
