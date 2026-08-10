#!/usr/bin/env python3
"""Audit a saved provider payload against endpoint-specific mappings."""

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
from alertissimo.data_layer.runtime.mapping_schema import validate_mapping_file
from alertissimo.data_layer.runtime.payload_paths import RawFieldMissing, extract_raw_field, resolve_payload_items
from alertissimo.data_layer.runtime.record_builder import build_portfolio_from_execution


def audit_payload(payload: Any, *, broker: str, origin: str, endpoint: str, payload_file: str) -> str:
    """Return the stable plain-text coverage report for one saved response."""
    mappings_path = PROVIDERS_ROOT / broker / origin / "mappings.yaml"
    validate_mapping_file(mappings_path)
    document = yaml.safe_load(mappings_path.read_text(encoding="utf-8"))
    definitions = {
        key: definition for key, definition in document["payloads"].items()
        if definition["endpoint"] == endpoint
    }
    resolved = {
        key: resolve_payload_items(payload, payload_key=key, payload_path=definition["path"])
        for key, definition in definitions.items()
    }

    successes: set[str] = set()
    missing: set[str] = set()
    represented: set[str] = set()
    for semantic_path, references in document["mappings"].items():
        relevant = [reference for reference in references if reference.split("#", 1)[0] in definitions]
        for reference in relevant:
            payload_key, raw_path = reference.split("#", 1)
            represented.add(raw_path.split(".", 1)[0])
            found = False
            for item in resolved[payload_key]:
                try:
                    extract_raw_field(item.value, raw_path)
                except RawFieldMissing:
                    continue
                found = True
                break
            (successes if found else missing).add(semantic_path)

    if isinstance(payload, dict):
        top_keys = sorted(payload)
    else:
        top_keys = []
    unmapped = sorted(set(top_keys) - represented)
    provenance = InternalExecutionProvenance(
        internal_execution_id=InternalExecutionId("execution:local:payload-audit"),
        broker=broker, origin=origin, endpoint=endpoint, params={}, status="success",
    )
    portfolio = connect_portfolio_records(build_portfolio_from_execution(
        ExecutionResult(payload=payload, execution_provenance=provenance)
    ))
    semantic_types = sorted({record.semantic_type for record in portfolio.records})

    lines = [
        f"Provider: {broker} / {origin}", f"Endpoint: {endpoint}",
        f"Payload file: {Path(payload_file).name}", "", "Payload shape:",
        "- top-level keys: " + (", ".join(top_keys) or "none"),
    ]
    if isinstance(payload, dict):
        for key in top_keys:
            value = payload[key]
            kind = "object" if isinstance(value, dict) else "list" if isinstance(value, list) else type(value).__name__
            size = len(value) if isinstance(value, (dict, list)) else 1
            lines.append(f"- {key}: {kind}[{size}]")
    lines.extend(["", "Mapping payload definitions for endpoint:"])
    if definitions:
        for key, definition in definitions.items():
            lines.append(f"- {key}: path {definition['path']!r} -> {len(resolved[key])} item(s)")
    else:
        lines.append("- none")
    lines.extend(["", "Resolved mapped fields:"] + ([f"- {path}" for path in sorted(successes)] or ["- none"]))
    lines.extend(["", "Mapped fields with missing raw refs:"] + ([f"- {path}" for path in sorted(missing)] or ["- none"]))
    lines.extend(["", "Unmapped top-level branches:"] + ([f"- {key}" for key in unmapped] or ["- none"]))
    lines.extend(["", "Portfolio:", f"- records: {len(portfolio.records)}",
                  "- semantic record types: " + (", ".join(semantic_types) or "none"),
                  f"- edges: {len(portfolio.edges)}"])
    if not portfolio.records:
        lines.extend(["", "Diagnostic:",
            "No semantic records were built for this endpoint/payload shape.",
            "This usually means mappings.yaml has no payload definition matching this endpoint shape."])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--broker", required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("payload", type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.payload.read_text(encoding="utf-8"))
        print(audit_payload(payload, broker=args.broker, origin=args.origin,
                            endpoint=args.endpoint, payload_file=str(args.payload)), end="")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
