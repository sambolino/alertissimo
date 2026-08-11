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
from alertissimo.data_layer.runtime.record_builder import build_portfolio_from_execution
from alertissimo.data_layer.runtime.serialization import portfolio_to_json


def build_portfolio_from_payload(payload: Any, *, endpoint: str = "object") -> Portfolio:
    """Build a portfolio from one previously saved Lasair object response."""
    object_id = payload.get("objectId") if isinstance(payload, dict) else None
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
    portfolio = build_portfolio_from_execution(
        execution,
        validate_semantic_model=True,
    )
    return connect_portfolio_records(portfolio)


def _print_summary(payload: Any, portfolio: Portfolio, endpoint: str) -> None:
    semantic_types = sorted({record.semantic_type for record in portfolio.records})
    print(f"endpoint: {endpoint}", file=sys.stderr)
    if isinstance(payload, dict):
        print(f"payload keys: {', '.join(sorted(payload))}", file=sys.stderr)
    else:
        print("payload type: list", file=sys.stderr)
        print(f"payload items: {len(payload)}", file=sys.stderr)
    print(f"records built: {len(portfolio.records)}", file=sys.stderr)
    print(f"semantic types: {', '.join(semantic_types)}", file=sys.stderr)
    print(f"edges built: {len(portfolio.edges)}", file=sys.stderr)
    if not portfolio.records:
        print("No semantic records were built for this endpoint/payload shape.", file=sys.stderr)


def _load_payload(path: Path) -> dict[str, Any] | list[Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON payload from {path}: {error}") from error
    if not isinstance(payload, (dict, list)):
        raise ValueError(f"payload in {path} must be a JSON object or array")
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
        portfolio = build_portfolio_from_payload(payload, endpoint=args.endpoint)
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.summary:
        _print_summary(payload, portfolio, args.endpoint)
    print(portfolio_to_json(portfolio))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
