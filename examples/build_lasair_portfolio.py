#!/usr/bin/env python3
"""Build a semantic portfolio from a small, offline Lasair-shaped payload."""

import sys
from pathlib import Path

# Make the source checkout importable when this file is executed directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance
from alertissimo.data_layer.runtime.record_builder import build_portfolio_from_execution
from alertissimo.data_layer.runtime.serialization import portfolio_to_json


payload = {
    "objectId": "ZTF25aazqavg",
    "objectData": {"ncand": 1, "jdmin": 2460000.5, "jdmax": 2460000.5, "ramean": 123.4, "decmean": 22.2},
    "candidates": [{"candid": 1, "jd": 2460000.5, "ra": 123.4, "dec": 22.2, "magpsf": 18.2, "sigmapsf": 0.08, "fid": 1}],
}
provenance = InternalExecutionProvenance(
    internal_execution_id=InternalExecutionId("execution:example:lasair"),
    broker="lasair", origin="ztf", endpoint="object", params={"objectId": payload["objectId"]}, status="success",
)
execution = ExecutionResult(payload=payload, execution_provenance=provenance)
portfolio = build_portfolio_from_execution(execution, validate_semantic_model=True)
print(portfolio_to_json(portfolio))
