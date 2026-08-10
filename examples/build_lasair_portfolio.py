#!/usr/bin/env python3
"""Build a semantic portfolio from a small, offline Lasair-shaped payload."""

import sys
from pathlib import Path

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


payload = {
    "objectId": "ZTF25aazqavg",
    "objectData": {
        "ncand": 2,
        "jdmin": 2460000.5,
        "jdmax": 2460003.5,
        "ramean": 123.4,
        "decmean": 22.2,
    },
    "candidates": [
        {"candid": 101, "jd": 2460000.5, "ra": 123.40, "dec": 22.20, "magpsf": 18.2, "sigmapsf": 0.08, "fid": 1, "drb": 0.93, "isdiffpos": "t"},
        {"candid": 102, "jd": 2460003.5, "ra": 123.42, "dec": 22.21, "magpsf": 18.7, "sigmapsf": 0.11, "fid": 2, "drb": 0.89, "isdiffpos": "t"},
    ],
    "sherlock": {"classification": "AGN", "classificationReliability": 0.86, "catalogue_object_id": "WISEA J081336.12+221200.3", "raDeg": 123.401, "decDeg": 22.201, "separationArcsec": 0.7},
    "TNS": {"name": "AT2026abc", "type": "SN Ia?", "ra": 123.405, "decl": 22.205, "z": 0.043},
}


def build_example_portfolio() -> Portfolio:
    """Build the deterministic seven-record Lasair dossier with no inferred edges."""
    provenance = InternalExecutionProvenance(
        internal_execution_id=InternalExecutionId("execution:example:lasair"),
        broker="lasair", origin="ztf", endpoint="object",
        params={"objectId": payload["objectId"]}, status="success",
    )
    execution = ExecutionResult(payload=payload, execution_provenance=provenance)
    portfolio = build_portfolio_from_execution(execution, validate_semantic_model=True)
    return connect_portfolio_records(portfolio)


def main() -> None:
    print(portfolio_to_json(build_example_portfolio()))


if __name__ == "__main__":
    main()
