#!/usr/bin/env python3
"""Report top-level payload branches not represented by broker mappings."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alertissimo.data_layer.paths import PROVIDERS_ROOT


def _top_level_payload_branch(payload_path: str) -> str | None:
    """Return the dict branch selected by the small payload-path notation."""
    if payload_path in {".", "[]"}:
        return None
    if payload_path.startswith("[]."):
        payload_path = payload_path[3:]
    first = payload_path.split(".", 1)[0]
    if first.endswith("[]"):
        first = first[:-2]
    return first or None


def _mapping_document(*, broker: str, origin: str) -> Mapping[str, Any]:
    path = PROVIDERS_ROOT / broker / origin / "mappings.yaml"
    with path.open(encoding="utf-8") as stream:
        document = yaml.safe_load(stream)
    if not isinstance(document, Mapping):
        raise ValueError(f"mapping file is not an object: {path}")
    return document


def _represented_top_level_branches(
    document: Mapping[str, Any], *, endpoint: str
) -> set[str]:
    """Find branches represented by payload definitions for one endpoint."""
    represented: set[str] = set()
    payloads = document.get("payloads", {})
    mappings = document.get("mappings", {})

    for payload_key, definition in payloads.items():
        if not isinstance(definition, Mapping) or definition.get("endpoint") != endpoint:
            continue
        payload_path = definition.get("path")
        if not isinstance(payload_path, str):
            continue

        branch = _top_level_payload_branch(payload_path)
        if branch is not None:
            represented.add(branch)

        # A root-object definition has no branch of its own. Its raw field
        # references are relative to the root and therefore identify branches.
        if payload_path != ".":
            continue
        prefix = f"{payload_key}#"
        for references in mappings.values():
            if not isinstance(references, list):
                continue
            for reference in references:
                if isinstance(reference, str) and reference.startswith(prefix):
                    raw_path = reference[len(prefix) :]
                    represented.add(raw_path.split(".", 1)[0])

    return represented


def audit_payload(
    payload: Any,
    *,
    broker: str,
    origin: str,
    endpoint: str,
    payload_file: str = "<payload>",
) -> str:
    """Return a deterministic human-readable mapping coverage report."""
    document = _mapping_document(broker=broker, origin=origin)
    represented = _represented_top_level_branches(document, endpoint=endpoint)
    top_level = set(payload) if isinstance(payload, Mapping) else set()
    unmapped = sorted(top_level - represented)

    lines = [
        "Payload mapping coverage",
        f"Payload: {payload_file}",
        f"Broker: {broker}",
        f"Origin: {origin}",
        f"Endpoint: {endpoint}",
        "",
        "Unmapped top-level branches:",
    ]
    lines.extend(f"- {branch}" for branch in unmapped)
    if not unmapped:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path)
    parser.add_argument("--broker", required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--endpoint", required=True)
    args = parser.parse_args()
    try:
        payload = json.loads(args.payload.read_text(encoding="utf-8"))
        report = audit_payload(
            payload,
            broker=args.broker,
            origin=args.origin,
            endpoint=args.endpoint,
            payload_file=str(args.payload),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
