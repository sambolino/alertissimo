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
    """Count plotted provider records, without treating them as unique observations."""
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


def _magnitude(fields: dict[str, Any]) -> tuple[str, float, float] | None:
    for key, value in fields.items():
        match = re.fullmatch(r"photometry\.([a-zA-Z0-9]+)\.psf\.mag", key)
        if not match or not isinstance(value, (int, float)) or not math.isfinite(value):
            continue
        error = fields.get(f"{key}.error", 0.0)
        return match.group(1), float(value), float(error) if isinstance(error, (int, float)) and math.isfinite(error) else 0.0
    return None


def classification_rows(portfolio: dict[str, Any]) -> list[dict[str, Any]]:
    """Project every named classification output with its own source and fields.

    These are transient presentation rows, not selected/merged scientific
    assertions. Probability and score remain different quantities, and neither
    payload order, version strings nor retrieval dates choose a winner.
    """
    records = [r for r in portfolio.get("records", []) if isinstance(r, dict)]
    executions = {e.get("internal_execution_id"): e for e in portfolio.get("executions", [])
                  if isinstance(e, dict)}

    def source_key(record):
        source = record.get("internal_source")
        if not isinstance(source, dict) or source.get("internal_execution_id") is None:
            return None
        # Incomplete legacy provenance cannot establish a shared physical row.
        if source.get("payload_key") is None or source.get("payload_path") is None:
            return None
        return tuple(source.get(k) for k in (
            "internal_execution_id", "payload_key", "payload_path", "payload_index",
        ))

    observations: dict[tuple, list[dict[str, Any]]] = {}
    for record in records:
        key = source_key(record)
        if _family(record) == "measurement" and key is not None:
            observations.setdefault(key, []).append(_fields(record))

    def associated(records, path):
        values = list(dict.fromkeys(str(r[path]) for r in records if r.get(path) is not None))
        return " · ".join(values) or None

    rows = []
    for record in records:
        if _family(record) != "classification":
            continue
        fields = _fields(record)
        source = record.get("internal_source")
        source = source if isinstance(source, dict) else {}
        execution = executions.get(source.get("internal_execution_id"), {})
        qualifier = str(record.get("semantic_type", "")).partition("@")[2]
        producer, _, channel = qualifier.partition(":")
        linked = observations.get(source_key(record), [])
        outputs = list(dict.fromkeys(
            "best" if key.startswith("best.") else ".".join(key.split(".")[:2])
            for key in fields if key.startswith(("best.", "assessment."))
        ))
        # A provenance-only classification is still material worth inspecting.
        for output in outputs or [""]:
            attributes = {key[len(output) + 1:]: value for key, value in fields.items()
                          if output and key.startswith(output + ".")}
            rows.append({
                "broker": execution.get("broker") or channel or None,
                "origin": execution.get("origin"),
                "producer": producer or None,
                "model": fields.get("provenance.producer.name") or producer or None,
                "version": fields.get("provenance.producer.version"),
                "output": output or None,
                "class": attributes.get("class"),
                "probability": attributes.get("probability"),
                "score": attributes.get("score"),
                "rank": attributes.get("rank"),
                "method": attributes.get("method", fields.get("provenance.producer.method")),
                "target": attributes.get("target"),
                "value": attributes.get("value", fields.get(output)),
                "description": attributes.get("description"),
                "other_values": {key: value for key, value in attributes.items() if key not in {
                    "class", "probability", "score", "rank", "method", "target", "value", "description",
                }},
                "observation_mjd": associated(linked, "time.mjd"),
                "source_id": associated(linked, "identity.source_id"),
                "assertion_mjd": fields.get("provenance.time.mjd"),
                "produced_mjd": fields.get("provenance.time.processed_mjd"),
                "assertion_datetime": fields.get("provenance.time.datetime"),
                "retrieved_at": execution.get("finished_at"),
                "endpoint": execution.get("endpoint"),
                "record_id": record.get("internal_record_id"),
                "semantic_type": record.get("semantic_type"),
                "execution_id": source.get("internal_execution_id"),
            })
    return rows


def classification_card_summary(data: dict[str, Any]) -> tuple[str, float | None]:
    """Summarize reported labels without selecting an authoritative assertion."""
    rows = data.get("classifications", [])
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
    for record in detections:
        fields = _fields(record)
        magnitude = _magnitude(fields)
        mjd = fields.get("time.mjd")
        if magnitude is None or not isinstance(mjd, (int, float)) or not math.isfinite(mjd):
            continue
        band, value, error = magnitude
        source = record.get("internal_source")
        execution_id = source.get("internal_execution_id") if isinstance(source, dict) else None
        execution = execution_index.get(execution_id, {}) if execution_id is not None else {}
        semantic_type = str(record.get("semantic_type", ""))
        origin, _, broker = semantic_type.partition("@")[2].partition(":")
        points.append({
            "date": pd.to_datetime(float(mjd), unit="D", origin="1858-11-17", utc=True).isoformat(),
            "mjd": float(mjd), "band": band, "magnitude": value, "magnitudeError": error,
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
        "ra": summary.get("position.ra") or next((_fields(record).get("position.ra") for record in detections if _fields(record).get("position.ra") is not None), None),
        "dec": summary.get("position.dec") or next((_fields(record).get("position.dec") for record in detections if _fields(record).get("position.dec") is not None), None),
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
        "summary": {"firstDetection": points[0]["date"] if points else "—", "lastDetection": points[-1]["date"] if points else "—", "brightestMagnitude": min((point["magnitude"] for point in points), default="—")},
        "quality": {"photometryStatus": f"{len(points)} plotted detections from normalized broker records", "alertQuality": "Recorded broker quality fields are available per detection.", "lastUpdated": "Frozen fixture"},
        "record_counts": counts,
    }
