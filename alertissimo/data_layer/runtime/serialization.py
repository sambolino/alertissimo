"""Stable, browser-friendly serialization for semantic portfolios."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from alertissimo.data_layer.representations import InternalRecordSource, Portfolio


def _plain(value: Any) -> Any:
    """Recursively copy immutable model values into JSON-compatible containers."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if hasattr(value, "value") and value.__class__.__name__.startswith("Internal"):
        return value.value
    return value


def _source_to_dict(source: InternalRecordSource | None) -> dict[str, Any] | None:
    if source is None:
        return None
    return {
        "internal_execution_id": source.internal_execution_id.value,
        "payload_key": source.payload_key,
        "payload_path": source.payload_path,
        "payload_index": source.payload_index,
    }


def portfolio_to_dict(portfolio: Portfolio) -> dict[str, Any]:
    """Return a deterministic plain-data representation without provider payloads."""
    executions = []
    for execution in portfolio.executions:
        executions.append({
            "internal_execution_id": execution.internal_execution_id.value,
            "broker": execution.broker,
            "origin": execution.origin,
            "endpoint": execution.endpoint,
            "params": _plain(execution.params),
            "status": execution.status,
            "started_at": execution.started_at,
            "finished_at": execution.finished_at,
            "payload_fingerprint": execution.payload_fingerprint,
            "registry_version": execution.registry_version,
            "adapter_version": execution.adapter_version,
            "elapsed_ms": execution.elapsed_ms,
            "transport": execution.transport,
            "method": execution.method,
            "url": execution.url,
            "response_status_code": execution.response_status_code,
            "response_content_type": execution.response_content_type,
            "raw_size_bytes": execution.raw_size_bytes,
        })
    records = [{
        "internal_record_id": record.internal_record_id.value,
        "semantic_type": record.semantic_type,
        "fields": _plain(record.fields),
        "internal_source": _source_to_dict(record.internal_source),
    } for record in portfolio.records]
    edges = [{
        "internal_edge_id": edge.internal_edge_id.value,
        "edge_type": edge.edge_type,
        "subject_record_id": edge.subject_record_id.value,
        "target_record_id": edge.target_record_id.value,
        "fields": _plain(edge.fields),
        "internal_source": _source_to_dict(edge.internal_source),
    } for edge in portfolio.edges]
    return {
        "internal_portfolio_id": portfolio.internal_portfolio_id.value,
        "executions": executions,
        "records": records,
        "edges": edges,
    }


def portfolio_to_json(portfolio: Portfolio, *, indent: int = 2) -> str:
    """Serialize a portfolio as deterministic JSON."""
    return json.dumps(portfolio_to_dict(portfolio), indent=indent, ensure_ascii=False)
