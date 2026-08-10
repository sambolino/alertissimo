"""Public value objects used by endpoint execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from alertissimo.core.portfolio import InternalExecutionId, InternalExecutionProvenance


@dataclass(frozen=True)
class EndpointSpec:
    broker: str
    origin: str
    endpoint: str
    transport_kind: str
    params: Mapping[str, Any] = field(default_factory=dict)
    fixed_params: Mapping[str, Any] = field(default_factory=dict)
    method: str | None = None
    url: str | None = None
    module: str | None = None
    client: str | None = None
    client_method: str | None = None
    headers: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("params", "fixed_params", "headers"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))


@dataclass(frozen=True)
class TransportResult:
    payload: Any
    method: str | None = None
    url: str | None = None
    status_code: int | None = None
    content_type: str | None = None
    sanitized_headers: Mapping[str, str] | None = None
    raw_size_bytes: int | None = None


@dataclass(frozen=True)
class ExecutionResult:
    payload: Any
    execution_provenance: InternalExecutionProvenance

    @property
    def internal_execution_id(self) -> InternalExecutionId:
        return self.execution_provenance.internal_execution_id
