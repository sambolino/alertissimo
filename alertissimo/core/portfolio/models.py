"""Canonical internal portfolio data contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class _InternalId:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value:
            raise ValueError("internal ID value must be a non-empty string")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class InternalPortfolioId(_InternalId):
    """Alertissimo identity for an internal portfolio."""


@dataclass(frozen=True)
class InternalRecordId(_InternalId):
    """Alertissimo identity for an internal semantic record."""


@dataclass(frozen=True)
class InternalEdgeId(_InternalId):
    """Alertissimo identity for an internal semantic edge."""


@dataclass(frozen=True)
class InternalExecutionId(_InternalId):
    """Alertissimo identity for one physical endpoint execution."""


@dataclass(frozen=True)
class InternalRecordSource:
    """Source information attached later when a semantic record is built."""

    internal_execution_id: InternalExecutionId
    payload_path: str


@dataclass(frozen=True)
class InternalExecutionProvenance:
    """Canonical, payload-free provenance for one endpoint execution."""

    internal_execution_id: InternalExecutionId
    broker: str
    origin: str
    endpoint: str
    params: Mapping[str, Any] = field(default_factory=dict)
    status: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_ms: float | None = None
    transport: str | None = None
    method: str | None = None
    url: str | None = None
    sanitized_headers: Mapping[str, str] | None = None
    response_status_code: int | None = None
    response_content_type: str | None = None
    raw_size_bytes: int | None = None
    payload_fingerprint: str | None = None
    registry_version: str | None = None
    adapter_version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))
        if self.sanitized_headers is not None:
            object.__setattr__(
                self,
                "sanitized_headers",
                MappingProxyType(dict(self.sanitized_headers)),
            )


@dataclass(frozen=True)
class SemanticRecord:
    internal_record_id: InternalRecordId
    record_type: str
    fields: Mapping[str, Any] = field(default_factory=dict)
    source: InternalRecordSource | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", MappingProxyType(dict(self.fields)))


@dataclass(frozen=True)
class SemanticEdge:
    internal_edge_id: InternalEdgeId
    source_record_id: InternalRecordId
    target_record_id: InternalRecordId
    relationship: str


@dataclass(frozen=True)
class Portfolio:
    internal_portfolio_id: InternalPortfolioId
    records: tuple[SemanticRecord, ...] = ()
    edges: tuple[SemanticEdge, ...] = ()
    execution_provenance: tuple[InternalExecutionProvenance, ...] = ()

