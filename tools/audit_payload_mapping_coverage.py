#!/usr/bin/env python3
"""Audit a saved broker payload against endpoint-specific semantic mappings."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance
from alertissimo.data_layer.runtime.edge_builder import connect_portfolio_records
from alertissimo.data_layer.runtime.payload_paths import RawFieldMissing, extract_raw_field, resolve_payload_items
from alertissimo.data_layer.runtime.record_builder import build_portfolio_from_execution
from tools.inspect_payload_shape import inspect_payload_shape


def _leaf_paths(value: Any, prefix: str = "") -> set[str]:
    """Return concrete leaf paths, collapsing homogeneous list rows."""
    if isinstance(value, dict):
        leaves: set[str] = set()
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            leaves.update(_leaf_paths(child, path))
        return leaves
    if isinstance(value, (list, tuple)):
        leaves: set[str] = set()
        indexed = all(not isinstance(child, (dict, list, tuple)) for child in value)
        for index, child in enumerate(value):
            child_prefix = f"{prefix}.{index}" if indexed else prefix
            leaves.update(_leaf_paths(child, child_prefix))
        return leaves
    return {prefix} if prefix else set()


def _delegated_roots(payload_path: str, definitions: dict[str, Any]) -> set[str]:
    """Find branches owned by definitions nested below this definition."""
    roots: set[str] = set()
    for definition in definitions.values():
        child = definition["path"]
        if child == payload_path:
            continue
        if payload_path == "." and not child.startswith("[]"):
            roots.add(child.split(".", 1)[0].removesuffix("[]").removesuffix("{}"))
        elif payload_path == "[]" and child.startswith("[]."):
            roots.add(child[3:].split(".", 1)[0].removesuffix("[]").removesuffix("{}"))
    return roots


def _mapping_document(broker: str, origin: str, providers_root: Path) -> tuple[Path, dict[str, Any]]:
    path = providers_root / broker / origin / "mappings.yaml"
    with path.open(encoding="utf-8") as stream:
        document = yaml.safe_load(stream)
    return path, document


def audit_payload(
    payload: Any,
    *,
    broker: str,
    origin: str,
    endpoint: str,
    payload_file: str = "<memory>",
    providers_root: Path | None = None,
) -> str:
    """Return a rich mapping and portfolio coverage report for one payload."""
    root = Path(providers_root) if providers_root is not None else PROVIDERS_ROOT
    mappings_path, document = _mapping_document(broker, origin, root)
    definitions = {
        key: definition
        for key, definition in document["payloads"].items()
        if definition["endpoint"] == endpoint
        and not (isinstance(payload, list) and definition["path"] == ".")
        and not (isinstance(payload, dict) and definition["path"] == "[]")
    }
    refs_by_payload: dict[str, list[tuple[str, str]]] = {key: [] for key in definitions}
    for semantic_path, references in document["mappings"].items():
        for reference in references:
            payload_key, raw_path = reference.split("#", 1)
            if payload_key in refs_by_payload:
                refs_by_payload[payload_key].append((semantic_path, raw_path))

    unmapped_path = mappings_path.with_name("unmapped_fields.yaml")
    unmapped_document = yaml.safe_load(unmapped_path.read_text(encoding="utf-8"))
    unmapped_by_payload: dict[str, set[str]] = {key: set() for key in definitions}
    for entry in unmapped_document.get("unmapped", []):
        reference = next(iter(entry))
        payload_key, raw_path = reference.split("#", 1)
        if payload_key in unmapped_by_payload:
            unmapped_by_payload[payload_key].add(raw_path)

    resolved: list[str] = []
    missing: list[str] = []
    mapped_leaves: set[str] = set()
    intentional_leaves: set[str] = set()
    delegated_leaves: set[str] = set()
    unaccounted_leaves: set[str] = set()
    observed_leaves: set[str] = set()
    for payload_key, definition in definitions.items():
        items = resolve_payload_items(payload, payload_key=payload_key, payload_path=definition["path"])
        delegated = _delegated_roots(definition["path"], definitions)
        mapped_raw = {raw for _, raw in refs_by_payload[payload_key]}
        for semantic_path, raw_path in refs_by_payload[payload_key]:
            reference = f"{payload_key}#{raw_path} -> {semantic_path}"
            if any(_has_raw_field(item.value, raw_path) for item in items):
                resolved.append(reference)
            else:
                missing.append(reference)
        for item in items:
            for raw_path in _leaf_paths(item.value):
                reference = f"{payload_key}#{raw_path}"
                root_name = raw_path.split(".", 1)[0]
                if root_name in delegated:
                    delegated_leaves.add(reference)
                    continue
                observed_leaves.add(reference)
                if raw_path in mapped_raw:
                    mapped_leaves.add(reference)
                elif raw_path in unmapped_by_payload[payload_key]:
                    intentional_leaves.add(reference)
                else:
                    unaccounted_leaves.add(reference)
    provenance = InternalExecutionProvenance(
        internal_execution_id=InternalExecutionId("execution:audit:payload"),
        broker=broker, origin=origin, endpoint=endpoint, params={}, status="success",
    )
    portfolio = connect_portfolio_records(build_portfolio_from_execution(
        ExecutionResult(payload=payload, execution_provenance=provenance),
        mappings_path=mappings_path,
        validate_semantic_model=True,
    ))
    semantic_types = sorted({record.semantic_type for record in portfolio.records})

    lines = [
        f"Provider: {broker}/{origin}", f"Endpoint: {endpoint}", f"Payload file: {payload_file}",
        "", "Payload shape:", *[f"  {line}" for line in inspect_payload_shape(payload)],
        "", "Mapping payload definitions for endpoint:",
        *([f"  {key}: {definition['path']}" for key, definition in definitions.items()] or ["  (none)"]),
        "", "Resolved mapped fields:", *([f"  {item}" for item in sorted(set(resolved))] or ["  (none)"]),
        "", "Mapped fields with missing raw refs:", *([f"  {item}" for item in sorted(set(missing))] or ["  (none)"]),
        "", "Unaccounted leaves:", *([f"  {item}" for item in sorted(unaccounted_leaves)] or ["  (none)"]),
        "", f"Observed leaves: {len(observed_leaves)}", f"Mapped leaves: {len(mapped_leaves)}",
        f"Intentionally unmapped leaves: {len(intentional_leaves)}",
        f"Delegated / structural leaves: {len(delegated_leaves)}",
        f"Unaccounted leaves: {len(unaccounted_leaves)}",
        "", f"Portfolio records: {len(portfolio.records)}",
        f"Semantic record types: {', '.join(semantic_types)}",
        f"Edges: {len(portfolio.edges)}",
    ]
    if not portfolio.records:
        lines.append("No semantic records were built for this endpoint/payload shape.")
    return "\n".join(lines) + "\n"


def _has_raw_field(value: Any, raw_path: str) -> bool:
    try:
        extract_raw_field(value, raw_path)
    except RawFieldMissing:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path)
    parser.add_argument("--broker", required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--endpoint", required=True)
    args = parser.parse_args()
    try:
        payload = json.loads(args.payload.read_text(encoding="utf-8"))
        print(audit_payload(payload, broker=args.broker, origin=args.origin, endpoint=args.endpoint,
                            payload_file=str(args.payload)), end="")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
