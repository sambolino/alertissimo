"""Value objects used at the broker endpoint execution boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from alertissimo.core.portfolio.models import InternalExecutionProvenance


@dataclass(frozen=True)
class EndpointSpec:
    broker: str
    origin: str
    endpoint: str
    transport_kind: str
    method: str
    path: str
    baseurl: str | None = None
    params: Mapping[str, Any] = field(default_factory=dict)
    headers: Mapping[str, Any] = field(default_factory=dict)
    fixed_params: Mapping[str, Any] = field(default_factory=dict)

    @property
    def url(self) -> str | None:
        if self.baseurl is None:
            return None
        return f"{self.baseurl.rstrip('/')}/{self.path.lstrip('/')}"


@dataclass(frozen=True)
class EndpointExecutionResult:
    """A broker-native response paired with call-scoped provenance."""

    payload: Any
    provenance: InternalExecutionProvenance
