"""Canonical, broker-independent in-memory portfolio representation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping


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


class PortfolioModelError(ValueError):
    """Raised when objects do not form a valid internal portfolio."""


def _copy_mapping(value: Mapping[str, Any], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PortfolioModelError(f"{name} must be a mapping")
    result = deepcopy(dict(value))
    for path in result:
        if not isinstance(path, str) or not path or path.startswith(("/", ".", "$")):
            raise PortfolioModelError(f"{name} paths must be non-empty and relative: {path!r}")
    return result


@dataclass(frozen=True)
class InternalRecordSource:
    """Call-scoped location from which a semantic record was extracted."""

    internal_execution_id: InternalExecutionId
    payload_key: str
    payload_path: str = ""
    payload_index: int | None = None

    def __post_init__(self) -> None:
        if self.payload_index is not None and self.payload_index < 0:
            raise PortfolioModelError("payload_index must be non-negative")


@dataclass(frozen=True)
class InternalExecutionProvenance:
    """Internal, call-scoped provenance for one endpoint execution."""

    internal_execution_id: InternalExecutionId
    broker: str
    origin: str
    endpoint: str
    params: Mapping[str, Any] = field(default_factory=dict)
    status: str = "success"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    elapsed_ms: float | None = None
    transport: str | None = None
    method: str | None = None
    url: str | None = None
    sanitized_headers: Mapping[str, str] | None = None
    response_status_code: int | None = None
    response_content_type: str | None = None
    raw_size_bytes: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", deepcopy(dict(self.params)))
        if self.sanitized_headers is not None:
            object.__setattr__(
                self, "sanitized_headers", deepcopy(dict(self.sanitized_headers))
            )


@dataclass(frozen=True)
class SemanticRecord:
    internal_record_id: InternalRecordId
    semantic_type: str
    fields: Mapping[str, Any]
    internal_source: InternalRecordSource

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", _copy_mapping(self.fields, "fields"))

    def get(self, path: str, default: Any = None) -> Any:
        """Return a semantic field without exposing storage details."""
        return self.fields.get(path, default)


@dataclass(frozen=True)
class SemanticEdge:
    internal_edge_id: InternalEdgeId
    edge_type: str
    subject_record_id: InternalRecordId
    target_record_id: InternalRecordId
    fields: Mapping[str, Any]
    internal_source: InternalRecordSource

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", _copy_mapping(self.fields, "fields"))

    def get(self, path: str, default: Any = None) -> Any:
        return self.fields.get(path, default)


@dataclass(frozen=True)
class Portfolio:
    internal_portfolio_id: InternalPortfolioId
    records: tuple[SemanticRecord, ...] = ()
    edges: tuple[SemanticEdge, ...] = ()
    executions: tuple[InternalExecutionProvenance, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(deepcopy(self.records)))
        object.__setattr__(self, "edges", tuple(deepcopy(self.edges)))
        object.__setattr__(self, "executions", tuple(deepcopy(self.executions)))
        self._validate_unique(self.records, "internal_record_id", "record")
        self._validate_unique(self.edges, "internal_edge_id", "edge")
        self._validate_unique(self.executions, "internal_execution_id", "execution")
        record_ids = {record.internal_record_id for record in self.records}
        for edge in self.edges:
            if edge.subject_record_id not in record_ids:
                raise PortfolioModelError(
                    f"edge subject does not exist: {edge.subject_record_id}"
                )
            if edge.target_record_id not in record_ids:
                raise PortfolioModelError(
                    f"edge target does not exist: {edge.target_record_id}"
                )

    @staticmethod
    def _validate_unique(items: tuple[Any, ...], attribute: str, kind: str) -> None:
        values = [getattr(item, attribute) for item in items]
        if len(values) != len(set(values)):
            raise PortfolioModelError(f"duplicate {kind} ID")

    def record(self, record_id: InternalRecordId) -> SemanticRecord:
        for record in self.records:
            if record.internal_record_id == record_id:
                return record
        raise KeyError(record_id)

    def execution(
        self, execution_id: InternalExecutionId
    ) -> InternalExecutionProvenance:
        for execution in self.executions:
            if execution.internal_execution_id == execution_id:
                return execution
        raise KeyError(execution_id)


__all__ = [
    "InternalEdgeId", "InternalExecutionId", "InternalExecutionProvenance",
    "InternalPortfolioId", "InternalRecordId", "InternalRecordSource",
    "Portfolio", "PortfolioModelError", "SemanticEdge", "SemanticRecord",
]
