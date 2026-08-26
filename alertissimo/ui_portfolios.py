"""Load generated, normalized Portfolio fixtures for the local Streamlit UI."""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance
from alertissimo.data_layer.runtime.record_builder import build_portfolios_from_execution
from alertissimo.data_layer.runtime.serialization import portfolio_to_dict

ROOT = Path(__file__).resolve().parents[1]
UI_PORTFOLIOS = ROOT / ".ui-fixtures" / "portfolios"

# One representative, real normalized Portfolio for every search-result page.
SEARCH_PORTFOLIOS = (
    "multibroker_lsst_170587117485817955.json",
    "ztf_alerce_ZTF18abbuksn.json",
    "ztf_antares_ZTF20aafqubg.json",
    "ztf_fink_ZTF21abfmbix.json",
)
DEFAULT_PORTFOLIO = "multibroker_lsst_170587117485817955.json"


def ensure_ui_portfolios() -> Path:
    """Build ignored UI output from frozen broker evidence when it is absent."""
    if not all((UI_PORTFOLIOS / name).is_file() for name in SEARCH_PORTFOLIOS):
        from scripts.build_ui_fixtures import build_corpus

        build_corpus(UI_PORTFOLIOS)
    return UI_PORTFOLIOS


def load_ui_portfolio(name: str) -> dict[str, Any]:
    """Load one generated Portfolio, never a legacy hand-authored demo document."""
    with (ensure_ui_portfolios() / name).open(encoding="utf-8") as source:
        data = json.load(source)
    if not isinstance(data, dict) or not isinstance(data.get("records"), list):
        raise ValueError(f"{name} is not a serialized Portfolio")
    return data


@lru_cache(maxsize=1)
def load_antares_ztf_cone_portfolios() -> tuple[dict[str, Any], ...]:
    """Normalize the frozen four-locus ANTARES ZTF cone-search response."""
    path = ROOT / "tests" / "fixtures" / "antares" / "ztf" / "cone_search.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    execution = ExecutionResult(
        payload=payload,
        execution_provenance=InternalExecutionProvenance(
            internal_execution_id=InternalExecutionId("execution:ui:antares:ztf:cone_search"),
            broker="antares", origin="ztf", endpoint="cone_search", params={}, status="frozen-fixture",
        ),
    )
    portfolios = build_portfolios_from_execution(execution, validate_semantic_model=True)
    return tuple(portfolio_to_dict(portfolio) for portfolio in portfolios)


def _family(record: dict[str, Any]) -> str:
    return str(record.get("semantic_type", "")).split("@", 1)[0]


def _fields(record: dict[str, Any]) -> dict[str, Any]:
    fields = record.get("fields")
    return fields if isinstance(fields, dict) else {}


def _first(records: list[dict[str, Any]], family: str) -> dict[str, Any]:
    return next((_fields(record) for record in records if _family(record) == family), {})


def records_by_family(data: dict[str, Any], family: str) -> tuple[dict[str, Any], ...]:
    """Select existing semantic records from a UI Portfolio projection.

    This is intentionally only a view over ``semantic_records``.  It does not
    construct or cache another scientific record representation.
    """

    records = data.get("semantic_records")
    if not isinstance(records, list):
        return ()
    return tuple(
        record
        for record in records
        if isinstance(record, dict) and record.get("family") == family
    )


def _summary_identity(records: list[dict[str, Any]]) -> tuple[str, str] | None:
    """Validate and return the one identity established by summary records."""

    identities: set[tuple[str, str]] = set()
    for record in records:
        if _family(record) != "summary":
            continue
        semantic_type = str(record.get("semantic_type", ""))
        _family_name, separator, qualifier = semantic_type.partition("@")
        origin, producer_separator, _producer = qualifier.partition(":")
        object_id = _fields(record).get("identity.object_id")
        if separator and producer_separator and origin and object_id is not None:
            identities.add((origin, str(object_id)))
    if len(identities) > 1:
        formatted = ", ".join(
            f"{origin}/{object_id}" for origin, object_id in sorted(identities)
        )
        raise ValueError(
            "Portfolio contains conflicting summary object identities: " + formatted
        )
    return next(iter(identities)) if identities else None


def _magnitude(fields: dict[str, Any]) -> tuple[str, float, float] | None:
    for key, value in fields.items():
        match = re.fullmatch(r"photometry\.([a-zA-Z0-9]+)\.psf\.mag", key)
        if not match or not isinstance(value, (int, float)) or not math.isfinite(value):
            continue
        error = fields.get(f"{key}.error", 0.0)
        return match.group(1), float(value), float(error) if isinstance(error, (int, float)) and math.isfinite(error) else 0.0
    return None


def _classification(fields: dict[str, Any]) -> tuple[Any, Any]:
    label = fields.get("best.class")
    probability = fields.get("best.probability", fields.get("best.score"))
    if label is None:
        label = next((value for key, value in fields.items() if key.endswith(".class")), None)
    if probability is None:
        probability = next((value for key, value in fields.items() if key.endswith((".probability", ".score"))), None)
    return label, probability


def portfolio_to_display(portfolio: dict[str, Any]) -> dict[str, Any]:
    """Project canonical records into the existing Streamlit presentation shape.

    The projection is deliberately lossy only for layout: all scientific values
    displayed originate in ``Portfolio.records`` and the actual records remain
    available in the Semantic Records tab.
    """
    records = [record for record in portfolio["records"] if isinstance(record, dict)]
    summary_identity = _summary_identity(records)
    summary = _first(records, "summary")
    detections = [record for record in records if _family(record) == "detection"]
    points = []
    for record in detections:
        fields = _fields(record)
        magnitude = _magnitude(fields)
        mjd = fields.get("time.mjd")
        if magnitude is None or not isinstance(mjd, (int, float)) or not math.isfinite(mjd):
            continue
        band, value, error = magnitude
        points.append({
            "date": pd.to_datetime(float(mjd), unit="D", origin="1858-11-17", utc=True).isoformat(),
            "mjd": float(mjd), "band": band, "magnitude": value, "magnitudeError": error,
            "details": fields, "record_id": record.get("internal_record_id"),
        })
    points.sort(key=lambda point: point["mjd"])

    object_id = (summary_identity[1] if summary_identity is not None else None) or next(
        (_fields(record).get("identity.object_id") for record in detections if _fields(record).get("identity.object_id") is not None),
        "Object",
    )
    coordinates = {
        "ra": summary.get("position.ra") or next((_fields(record).get("position.ra") for record in detections if _fields(record).get("position.ra") is not None), None),
        "dec": summary.get("position.dec") or next((_fields(record).get("position.dec") for record in detections if _fields(record).get("position.dec") is not None), None),
    }
    classifications = []
    for record in records:
        if _family(record) != "classification":
            continue
        fields = _fields(record)
        label, probability = _classification(fields)
        semantic_type = str(record.get("semantic_type", ""))
        source, _, broker = semantic_type.partition("@")
        classifications.append({"broker": broker or source, "model": fields.get("provenance.producer.name", source), "class": label, "probability": probability})
    execution_rows = []
    for execution in portfolio.get("executions", []):
        if not isinstance(execution, dict):
            continue
        execution_id = execution.get("internal_execution_id")
        execution_rows.append({
            "broker": execution.get("broker"), "origin": execution.get("origin"),
            "endpoint": execution.get("endpoint"), "status": execution.get("status"),
            "records": sum(record.get("internal_source", {}).get("internal_execution_id") == execution_id for record in records if isinstance(record.get("internal_source"), dict)),
        })
    broker_coverage = [{"broker": row["broker"], "origin": row["origin"], "status": row["status"], "products": [row["endpoint"]]} for row in execution_rows]
    semantic_records = [{
        "record_id": record.get("internal_record_id", "—"), "semantic_type": record.get("semantic_type", "—"),
        "family": _family(record), "fields": _fields(record),
    } for record in records]
    counts = Counter(_family(record) for record in records)
    return {
        "diaObjectId": str(object_id), "survey": next((row["origin"] for row in execution_rows if row["origin"]), "—").upper(),
        "coordinates": coordinates, "filters": dict(Counter(point["band"] for point in points)),
        "lightCurve": points, "classifications": classifications, "context": {"host": {}, "crossmatches": [item["fields"] for item in semantic_records if item["family"] == "crossmatch"], "solarSystem": {}},
        "dataProducts": [item["fields"] for item in semantic_records if item["family"] == "data_product"],
        "brokerCoverage": broker_coverage, "provenance": execution_rows, "semantic_records": semantic_records,
        "summary": {"firstDetection": points[0]["date"] if points else "—", "lastDetection": points[-1]["date"] if points else "—", "brightestMagnitude": min((point["magnitude"] for point in points), default="—")},
        "quality": {"photometryStatus": f"{len(points)} plotted detections from normalized broker records", "alertQuality": "Recorded broker quality fields are available per detection.", "lastUpdated": "Frozen fixture"},
        "record_counts": counts,
    }
