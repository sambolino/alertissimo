"""Data contracts for endpoint execution.

Payloads in these models remain broker-native. Semantic mapping belongs to a
later pipeline step.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from alertissimo.core.internal import InternalExecutionId


@dataclass(frozen=True)
class RequestMetadata:
    method: str | None
    url: str | None
    params: dict[str, Any]
    sanitized_headers: dict[str, str] | None = None


@dataclass(frozen=True)
class ResponseMetadata:
    status_code: int | None = None
    content_type: str | None = None
    raw_size_bytes: int | None = None


@dataclass(frozen=True)
class ExecutionMetadata:
    broker: str
    origin: str
    endpoint: str
    transport: str
    started_at: datetime
    completed_at: datetime
    elapsed_ms: float
    request: RequestMetadata
    response: ResponseMetadata


@dataclass(frozen=True)
class ExecutionResult:
    payload: Any
    internal_execution_id: InternalExecutionId
    metadata: ExecutionMetadata


@dataclass(frozen=True)
class TransportResult:
    payload: Any
    method: str | None = None
    url: str | None = None
    status_code: int | None = None
    content_type: str | None = None
    sanitized_headers: dict[str, str] | None = None
    raw_size_bytes: int | None = None


@dataclass(frozen=True)
class PayloadBinding:
    """A broker-native payload root declared by a mappings.yaml file."""

    name: str
    path: str


@dataclass(frozen=True)
class EndpointSpec:
    """Normalized physical endpoint contract assembled from registry YAML."""

    broker: str
    origin: str
    name: str
    transport_kind: str
    method: str | None
    path: str | None
    base_url: str | None
    params: Mapping[str, Mapping[str, Any]]
    fixed_params: Mapping[str, Any]
    operation_types: tuple[str, ...]
    payloads: tuple[PayloadBinding, ...]
    semantic_paths: tuple[str, ...]

    @property
    def url(self) -> str | None:
        if not self.path or not self.base_url:
            return None
        return f"{self.base_url.rstrip('/')}/{self.path.lstrip('/')}"


__all__ = [
    "EndpointSpec",
    "ExecutionMetadata",
    "ExecutionResult",
    "PayloadBinding",
    "RequestMetadata",
    "ResponseMetadata",
    "TransportResult",
]
