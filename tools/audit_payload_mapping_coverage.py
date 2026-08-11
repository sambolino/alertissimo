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


def _top_level_payload_branch(payload_path: str) -> str | None:
    """Return the payload branch selected by the deliberately small path syntax."""
    if payload_path in {".", "[]"}:
        return None
    if payload_path.startswith("[]."):
        payload_path = payload_path[3:]
    first = payload_path.split(".", 1)[0]
    if first.endswith(("[]", "{}")):
        first = first[:-2]
    return first or None


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
    }
    refs_by_payload: dict[str, list[tuple[str, str]]] = {key: [] for key in definitions}
    for semantic_path, references in document["mappings"].items():
        for reference in references:
            payload_key, raw_path = reference.split("#", 1)
            if payload_key in refs_by_payload:
                refs_by_payload[payload_key].append((semantic_path, raw_path))

    represented: set[str] = set()
    resolved: list[str] = []
    missing: list[str] = []
    for payload_key, definition in definitions.items():
        branch = _top_level_payload_branch(definition["path"])
        if branch is not None:
            represented.add(branch)
        items = resolve_payload_items(payload, payload_key=payload_key, payload_path=definition["path"])
        for semantic_path, raw_path in refs_by_payload[payload_key]:
            reference = f"{payload_key}#{raw_path} -> {semantic_path}"
            if any(_has_raw_field(item.value, raw_path) for item in items):
                resolved.append(reference)
            else:
                missing.append(reference)
            # Root-object refs are relative to the payload and therefore identify branches.
            if definition["path"] == ".":
                represented.add(raw_path.split(".", 1)[0])

    top_level = set(payload) if isinstance(payload, dict) else set()
    unmapped = sorted(top_level - represented)
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
        "", "Unmapped top-level branches:", *([f"  {item}" for item in unmapped] or ["  (none)"]),
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
