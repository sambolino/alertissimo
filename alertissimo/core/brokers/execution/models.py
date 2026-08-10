"""Value objects shared by endpoint registries, transports, and executors."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from alertissimo.core.portfolio import InternalExecutionId, InternalExecutionProvenance


@dataclass(frozen=True)
class PayloadBinding:
    """Describe where a parameter is sent by a physical transport."""

    location: str = "auto"
    name: str | None = None


@dataclass(frozen=True)
class EndpointSpec:
    broker: str
    origin: str
    endpoint: str
    method: str
    path: str
    baseurl: str | None = None
    params: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    headers: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    transport_kind: str = "rest"

    @property
    def url(self) -> str | None:
        if self.transport_kind == "python_client":
            return None
        if self.path.startswith(("http://", "https://")):
            return self.path
        return f"{(self.baseurl or '').rstrip('/')}/{self.path.lstrip('/')}"


@dataclass(frozen=True)
class TransportResult:
    payload: Any
    method: str | None = None
    url: str | None = None
    sanitized_headers: Mapping[str, str] | None = None
    status_code: int | None = None
    content_type: str | None = None
    raw_size_bytes: int | None = None


@dataclass(frozen=True)
class ExecutionResult:
    payload: Any
    execution_provenance: InternalExecutionProvenance

    @property
    def internal_execution_id(self) -> InternalExecutionId:
        return self.execution_provenance.internal_execution_id
