#!/usr/bin/env python3
"""Build a semantic portfolio from a saved Lasair ZTF object payload."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Make the source checkout importable when this file is executed directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
    Portfolio,
)
from alertissimo.data_layer.runtime.edge_builder import connect_portfolio_records
from alertissimo.data_layer.runtime.record_builder import build_portfolios_from_execution
from alertissimo.data_layer.runtime.serialization import portfolio_to_json


def build_portfolios_from_payload(
    payload: dict[str, Any], *, endpoint: str = "object"
) -> tuple[Portfolio, ...]:
    """Build zero or more portfolios from a previously saved Lasair response."""
    object_id = payload.get("objectId")
    params = {"objectId": object_id} if object_id is not None else {}
    provenance = InternalExecutionProvenance(
        internal_execution_id=InternalExecutionId("execution:local:lasair-payload"),
        broker="lasair",
        origin="ztf",
        endpoint=endpoint,
        params=params,
        status="success",
    )
    execution = ExecutionResult(
        payload=payload,
        execution_provenance=provenance,
    )
    portfolios = build_portfolios_from_execution(
        execution,
        validate_semantic_model=True,
    )
    return tuple(connect_portfolio_records(portfolio) for portfolio in portfolios)


def build_portfolio_from_payload(payload: dict[str, Any], *, endpoint: str = "object") -> Portfolio:
    """Build exactly one portfolio from a saved single-object Lasair response."""
    portfolios = build_portfolios_from_payload(payload, endpoint=endpoint)
    if len(portfolios) != 1:
        raise ValueError(
            "expected exactly one Portfolio from execution, "
            f"but normalization produced {len(portfolios)}"
        )
    return portfolios[0]


def _print_summary(
    payload: dict[str, Any], portfolios: tuple[Portfolio, ...], endpoint: str
) -> None:
    records = tuple(record for portfolio in portfolios for record in portfolio.records)
    semantic_types = sorted({record.semantic_type for record in records})
    print(f"endpoint: {endpoint}", file=sys.stderr)
    print(f"payload keys: {', '.join(sorted(payload))}", file=sys.stderr)
    print(f"portfolios built: {len(portfolios)}", file=sys.stderr)
    print(f"records built: {len(records)}", file=sys.stderr)
    print(f"semantic types: {', '.join(semantic_types)}", file=sys.stderr)
    print(f"edges built: {sum(len(portfolio.edges) for portfolio in portfolios)}", file=sys.stderr)
    if not records:
        print("No semantic records were built for this endpoint/payload shape.", file=sys.stderr)


def _load_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON payload from {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"payload in {path} must be a JSON object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path, help="saved Lasair object JSON response")
    parser.add_argument("--endpoint", default="object", help="Lasair endpoint that produced the payload")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="write payload and portfolio diagnostics to stderr",
    )
    args = parser.parse_args()

    try:
        payload = _load_payload(args.payload)
        portfolios = build_portfolios_from_payload(payload, endpoint=args.endpoint)
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.summary:
        _print_summary(payload, portfolios, args.endpoint)
    if len(portfolios) == 1:
        print(portfolio_to_json(portfolios[0]))
    else:
        print(json.dumps([json.loads(portfolio_to_json(p)) for p in portfolios]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
