#!/usr/bin/env python3
"""Live Lasair -> ExecutionResult -> semantic Portfolio -> dossier HTML smoke test."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import webbrowser

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alertissimo.data_layer.execution import RegistryEndpointExecutor
from alertissimo.data_layer.presentation import write_portfolio_html
from alertissimo.data_layer.runtime.edge_builder import connect_portfolio_records
from alertissimo.data_layer.runtime.record_builder import build_portfolio_from_execution

DEFAULT_OBJECTS = {"lsst": "313761042336317573", "ztf": "ZTF20acpwljl"}


def load_env(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", choices=("lsst", "ztf"), default="lsst")
    parser.add_argument("--object-id")
    parser.add_argument("--output", type=Path, default=Path("/tmp/portfolio.html"))
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    load_env(args.env_file)
    token_var = f"LASAIR_{args.origin.upper()}_TOKEN"
    token = os.environ.get(token_var)
    if not token:
        print(f"error: {token_var} not found in environment or {args.env_file}", file=sys.stderr)
        return 2

    object_id = args.object_id or DEFAULT_OBJECTS[args.origin]
    print(f"Live execution: lasair/{args.origin}/object")
    print(f"Object:         {object_id}")
    print(f"Credential:     {token_var} (value hidden)")

    executor = RegistryEndpointExecutor()
    try:
        execution = executor.execute(
            "lasair", args.origin, "object", {"objectId": object_id},
            headers={"Authorization": f"Token {token}"},
        )
    except Exception as error:
        print(f"\nLIVE EXECUTION FAILED: {type(error).__name__}: {error}", file=sys.stderr)
        print(
            "Check the endpoint's declared request encoding and the provider response status.",
            file=sys.stderr,
        )
        return 1

    p = execution.execution_provenance
    print(f"Execution OK:   HTTP {p.response_status_code}, {p.raw_size_bytes} bytes")

    try:
        portfolio = build_portfolio_from_execution(execution, validate_semantic_model=True)
        portfolio = connect_portfolio_records(portfolio)
    except Exception as error:
        print(f"\nPORTFOLIO BUILD FAILED: {type(error).__name__}: {error}", file=sys.stderr)
        return 1

    output = write_portfolio_html(portfolio, args.output)
    semantic_types = sorted({record.semantic_type for record in portfolio.records})
    print(f"Portfolio OK:   {len(portfolio.records)} records, {len(portfolio.edges)} edges")
    print(f"Semantic types: {len(semantic_types)}")
    for semantic_type in semantic_types:
        print(f"  - {semantic_type}")
    print(f"HTML:           {output}")

    if not args.no_open:
        webbrowser.open(output.resolve().as_uri())
        print("Browser:        open requested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
