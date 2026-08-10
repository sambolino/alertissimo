"""Canonical, broker-independent portfolio data model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping


class PortfolioModelError(ValueError):
    """Raised when portfolio data violates an internal model invariant."""


@dataclass(frozen=True)
class _InternalId:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value:
            raise PortfolioModelError("internal ID value must be a non-empty string")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class InternalPortfolioId(_InternalId):
    pass


@dataclass(frozen=True)
class InternalRecordId(_InternalId):
    pass


@dataclass(frozen=True)
class InternalEdgeId(_InternalId):
    pass


@dataclass(frozen=True)
class InternalExecutionId(_InternalId):
    pass


def _frozen_mapping(value: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PortfolioModelError(f"{name} must be a mapping")
    return MappingProxyType(dict(value))


def _validate_fields(value: Mapping[str, Any]) -> Mapping[str, Any]:
    copied = _frozen_mapping(value, "fields")
    for key in copied:
        if not isinstance(key, str) or not key:
            raise PortfolioModelError("field keys must be non-empty strings")
        if key.startswith("$.") or key.startswith(".") or key.startswith("/"):
            raise PortfolioModelError(f"field key must be relative: {key!r}")
        if "@" in key or key.startswith("portfolio.") or "--" in key:
            raise PortfolioModelError(f"invalid relative field key: {key!r}")
    return copied


@dataclass(frozen=True)
class InternalRecordSource:
    """Call-scoped source of a semantic record or edge."""

    internal_execution_id: InternalExecutionId
    payload_path: str | None = None


@dataclass(frozen=True)
class InternalExecutionProvenance:
    internal_execution_id: InternalExecutionId
    broker: str
    origin: str
    endpoint: str
    params: Mapping[str, Any]
    started_at: datetime
    finished_at: datetime
    status: str
    elapsed_ms: float | None = None
    transport: str | None = None
    method: str | None = None
    url: str | None = None
    sanitized_headers: Mapping[str, str] | None = None
    response_status_code: int | None = None
    response_content_type: str | None = None
    raw_size_bytes: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", _frozen_mapping(self.params, "params"))
        if self.sanitized_headers is not None:
            object.__setattr__(
                self,
                "sanitized_headers",
                _frozen_mapping(self.sanitized_headers, "sanitized_headers"),
            )


@dataclass(frozen=True)
class SemanticRecord:
    internal_record_id: InternalRecordId
    semantic_type: str
    fields: Mapping[str, Any] = field(default_factory=dict)
    internal_source: InternalRecordSource | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.semantic_type, str) or not self.semantic_type:
            raise PortfolioModelError("semantic_type must be a non-empty string")
        object.__setattr__(self, "fields", _validate_fields(self.fields))

    def get(self, key: str, default: Any = None) -> Any:
        return self.fields.get(key, default)

    def has(self, key: str) -> bool:
        return key in self.fields


@dataclass(frozen=True)
class SemanticEdge:
    internal_edge_id: InternalEdgeId
    edge_type: str
    subject_record_id: InternalRecordId
    target_record_id: InternalRecordId
    fields: Mapping[str, Any] = field(default_factory=dict)
    internal_source: InternalRecordSource | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.edge_type, str) or not (
            self.edge_type.startswith("--")
            and (self.edge_type.endswith("--") or self.edge_type.endswith("-->"))
            and len(self.edge_type) > 4
        ):
            raise PortfolioModelError(
                "edge_type must use connection-plane --edge-- syntax"
            )
        object.__setattr__(self, "fields", _validate_fields(self.fields))

    def get(self, key: str, default: Any = None) -> Any:
        return self.fields.get(key, default)

    def has(self, key: str) -> bool:
        return key in self.fields


@dataclass(frozen=True)
class Portfolio:
    internal_portfolio_id: InternalPortfolioId
    records: tuple[SemanticRecord, ...] = ()
    edges: tuple[SemanticEdge, ...] = ()
    executions: tuple[InternalExecutionProvenance, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "edges", tuple(self.edges))
        object.__setattr__(self, "executions", tuple(self.executions))
        record_ids = [item.internal_record_id for item in self.records]
        edge_ids = [item.internal_edge_id for item in self.edges]
        execution_ids = [item.internal_execution_id for item in self.executions]
        self._reject_duplicates(record_ids, "record")
        self._reject_duplicates(edge_ids, "edge")
        self._reject_duplicates(execution_ids, "execution")
        known_records = set(record_ids)
        for edge in self.edges:
            if edge.subject_record_id not in known_records or edge.target_record_id not in known_records:
                raise PortfolioModelError("edge participant IDs must exist in records")
        if self.executions:
            known_executions = set(execution_ids)
            for item in (*self.records, *self.edges):
                if item.internal_source is not None and item.internal_source.internal_execution_id not in known_executions:
                    raise PortfolioModelError("internal_source execution ID must exist in executions")

    @staticmethod
    def _reject_duplicates(values: list[_InternalId], kind: str) -> None:
        if len(values) != len(set(values)):
            raise PortfolioModelError(f"duplicate {kind} IDs are not allowed")

    def records_of_type(self, semantic_type: str) -> tuple[SemanticRecord, ...]:
        return tuple(r for r in self.records if r.semantic_type == semantic_type)

    def get_record(self, internal_record_id: InternalRecordId) -> SemanticRecord | None:
        return next((r for r in self.records if r.internal_record_id == internal_record_id), None)

    def get_edge(self, internal_edge_id: InternalEdgeId) -> SemanticEdge | None:
        return next((e for e in self.edges if e.internal_edge_id == internal_edge_id), None)

    def semantic_types(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(r.semantic_type for r in self.records))

    def edges_of_type(self, edge_type: str) -> tuple[SemanticEdge, ...]:
        return tuple(e for e in self.edges if e.edge_type == edge_type)

    def execution(self, internal_execution_id: InternalExecutionId) -> InternalExecutionProvenance | None:
        return next((e for e in self.executions if e.internal_execution_id == internal_execution_id), None)
