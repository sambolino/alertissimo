"""Shared projection of stored classification evidence; never rerun policies."""
from __future__ import annotations

from typing import Any

from alertissimo.data_layer.representations import Portfolio
from alertissimo.data_layer.runtime.serialization import portfolio_to_dict


def classification_rows(portfolio: Portfolio | dict[str, Any]) -> list[dict[str, Any]]:
    """Project every named classification output with its own source and fields.

    These are transient presentation rows, not selected/merged scientific
    assertions. Probability and score remain different quantities, and neither
    payload order, version strings nor retrieval dates choose a winner.
    """
    if isinstance(portfolio, Portfolio):
        portfolio = portfolio_to_dict(portfolio)
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
        if str(record.get("semantic_type", "")).partition("@")[0] == "measurement" and key is not None:
            observations.setdefault(key, []).append(record.get("fields", {}))

    def associated(records, path):
        values = list(dict.fromkeys(str(r[path]) for r in records if r.get(path) is not None))
        return " · ".join(values) or None

    rows = []
    for record in records:
        if str(record.get("semantic_type", "")).partition("@")[0] != "classification":
            continue
        fields = record.get("fields", {})
        source = record.get("internal_source")
        source = source if isinstance(source, dict) else {}
        execution = executions.get(source.get("internal_execution_id"), {})
        qualifier = str(record.get("semantic_type", "")).partition("@")[2]
        producer, _, channel = qualifier.partition(":")
        headline = producer == "headline"
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
                "origin": fields.get("best.survey") if headline else execution.get("origin"),
                "producer": producer or None,
                "model": fields.get("best.source_method") if headline else fields.get("provenance.producer.name") or producer or None,
                "version": fields.get("best.source_version") if headline else fields.get("provenance.producer.version"),
                "output": output or None,
                "class": attributes.get("native_class") if headline else attributes.get("class"),
                "headline": headline,
                "coarse_class": attributes.get("coarse_class") if headline else None,
                "scope": attributes.get("scope") if headline else None,
                "basis": attributes.get("basis") if headline else None,
                "candidate_status": attributes.get("candidate_status") if headline else None,
                "status": attributes.get("status") if headline else None,
                "policy": attributes.get("policy") if headline else None,
                "mapping_version": attributes.get("mapping_version") if headline else None,
                "policy_digest": attributes.get("policy_digest") if headline else None,
                "error": attributes.get("error_code") if headline else None,
                "selected_record_ids": attributes.get("selected_record_ids") if headline else None,
                "probability": attributes.get("native_probability") if headline else attributes.get("probability"),
                "score": attributes.get("native_score") if headline else attributes.get("score"),
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

