"""Load generated, normalized Portfolio fixtures for the local Streamlit UI."""
from __future__ import annotations

import json
import math
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from alertissimo.data_layer.presentation.portfolio_classification import classification_rows
from alertissimo.data_layer.presentation.portfolio_lightcurve import serialized_portfolio_lightcurve_dataframe

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
    """Refresh generated UI output when its frozen inputs or normalizer change."""
    from scripts.build_ui_fixtures import CORPUS_STAMP, build_corpus, corpus_fingerprint

    stamp = UI_PORTFOLIOS / CORPUS_STAMP
    current = corpus_fingerprint()
    if (not all((UI_PORTFOLIOS / name).is_file() for name in SEARCH_PORTFOLIOS)
            or not stamp.is_file() or stamp.read_text(encoding="utf-8").strip() != current):
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


def reported_detection_counts(data: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    """Project the latest dated count for each provider/object summary history.

    Unknown epochs and conflicting counts at the latest epoch remain visible;
    neither payload order nor the largest count proves which snapshot is latest.
    This selects metric values only and leaves all scientific records untouched.
    """

    groups: dict[tuple[str, str], list[tuple[str, Any, float | None]]] = {}
    for record in records_by_family(data, "summary"):
        fields = _fields(record)
        count = fields.get("detection_count")
        if count is None:
            continue
        semantic_type = str(record.get("semantic_type", ""))
        qualifier = semantic_type.partition("@")[2]
        broker = qualifier.partition(":")[2] or "unknown provider"
        object_id = str(fields.get("identity.object_id", data.get("diaObjectId", "")))
        epoch = fields.get("time.last_mjd")
        timestamp = (
            float(epoch)
            if isinstance(epoch, (int, float)) and not isinstance(epoch, bool) and math.isfinite(epoch)
            else None
        )
        groups.setdefault((semantic_type, object_id), []).append((broker, count, timestamp))

    result: list[tuple[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for snapshots in groups.values():
        latest = max((epoch for _, _, epoch in snapshots if epoch is not None), default=None)
        for broker, count, epoch in snapshots:
            if epoch is not None and epoch != latest:
                continue
            key = (broker, str(count))
            if key not in seen:
                seen.add(key)
                result.append((broker, count))
    return tuple(result)


def loaded_photometry_counts(data: dict[str, Any]) -> tuple[tuple[str, int], ...]:
    """Count plotted values, not unique records or independent observations."""
    counts = Counter(str(point.get("broker") or "unknown provider") for point in data.get("lightCurve", []))
    return tuple(sorted(counts.items()))


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


def latest_magnitude(display: dict[str, Any]) -> float | None:
    """Read the latest measured magnitude, excluding limits and flux values."""
    return next((point["magnitude"] for point in reversed(display.get("lightCurve", []))
                 if point.get("magnitude") is not None and not point.get("is_upper_limit", False)), None)



def classification_card_summary(data: dict[str, Any]) -> tuple[str, float | None]:
    """Summarize reported labels without selecting an authoritative assertion."""
    rows = data.get("classifications", [])
    selected = [row for row in rows if row.get("headline")]
    if selected:
        rows = selected
    labels = list(dict.fromkeys(str(r["class"]) for r in rows if r.get("class") is not None))
    label = labels[0] if len(labels) == 1 else f"{len(labels)} labels" if labels else "—"
    probability = rows[0].get("probability") if len(rows) == 1 and labels else None
    if (isinstance(probability, bool) or not isinstance(probability, (int, float))
            or not math.isfinite(probability) or not 0 <= probability <= 1):
        probability = None
    return label, probability


def portfolio_to_display(portfolio: dict[str, Any]) -> dict[str, Any]:
    """Project canonical records into the existing Streamlit presentation shape.

    The projection is deliberately lossy only for layout: all scientific values
    displayed originate in ``Portfolio.records`` and the actual records remain
    available in the Semantic Records tab.
    """
    records = [record for record in portfolio["records"] if isinstance(record, dict)]
    executions = [item for item in portfolio.get("executions", []) if isinstance(item, dict)]
    execution_index = {item.get("internal_execution_id"): item for item in executions}
    summary_identity = _summary_identity(records)
    summary = _first(records, "summary")
    detections = [record for record in records if _family(record) == "measurement"]
    points = []
    by_id = {record["internal_record_id"]: record for record in detections}
    for row in serialized_portfolio_lightcurve_dataframe(portfolio).to_dict("records"):
        record = by_id[row["record_id"]]
        fields = _fields(record)
        mjd, band, value = row["mjd"], row["band"], row["value"]
        error = row["error"] if pd.notna(row["error"]) else None
        source = record.get("internal_source")
        execution_id = source.get("internal_execution_id") if isinstance(source, dict) else None
        execution = execution_index.get(execution_id, {}) if execution_id is not None else {}
        semantic_type = str(record.get("semantic_type", ""))
        origin, _, broker = semantic_type.partition("@")[2].partition(":")
        points.append({
            "date": pd.to_datetime(float(mjd), unit="D", origin="1858-11-17", utc=True).isoformat(),
            "mjd": float(mjd), "band": band, "value": value, "error": error,
            "quantity": row["quantity"], "measurement_kind": row["measurement_kind"],
            "is_upper_limit": row["is_upper_limit"],
            "magnitude": value if row["quantity"] == "mag" else None,
            "magnitudeError": error if row["quantity"] == "mag" else None,
            "details": fields, "record_id": record.get("internal_record_id"),
            "semantic_type": semantic_type,
            "broker": execution.get("broker") or broker or None,
            "origin": execution.get("origin") or origin or None,
            "endpoint": execution.get("endpoint"),
            "real_bogus": fields.get("quality.real_bogus"),
        })
    points.sort(key=lambda point: point["mjd"])

    object_id = (summary_identity[1] if summary_identity is not None else None) or next(
        (_fields(record).get("identity.object_id") for record in detections if _fields(record).get("identity.object_id") is not None),
        "Object",
    )
    coordinates = {
        axis: summary.get(path) if summary.get(path) is not None else next(
            (_fields(record)[path] for record in detections if _fields(record).get(path) is not None), None)
        for axis, path in (("ra", "position.ra"), ("dec", "position.dec"))
    }
    classifications = classification_rows(portfolio)
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
        "internal_source": record.get("internal_source"),
    } for record in records]
    counts = Counter(_family(record) for record in records)
    return {
        "diaObjectId": str(object_id), "survey": next((row["origin"] for row in execution_rows if row["origin"]), "—").upper(),
        "coordinates": coordinates, "filters": dict(Counter(point["band"] for point in points)),
        "lightCurve": points, "classifications": classifications, "context": {"host": {}, "crossmatches": [item["fields"] for item in semantic_records if item["family"] == "crossmatch"], "solarSystem": {}},
        "dataProducts": [item["fields"] for item in semantic_records if item["family"] == "data_product"],
        "brokerCoverage": broker_coverage, "provenance": execution_rows, "semantic_records": semantic_records,
        "executions": executions,
        "summary": {"firstDetection": points[0]["date"] if points else "—", "lastDetection": points[-1]["date"] if points else "—", "brightestMagnitude": min((p["magnitude"] for p in points if p["magnitude"] is not None and not p["is_upper_limit"]), default="—")},
        "quality": {"photometryStatus": f"{len(points)} plotted photometric values from normalized records; several values may share one observation.", "alertQuality": "Recorded broker quality fields are available per measurement.", "lastUpdated": "See execution provenance"},
        "record_counts": counts,
    }
