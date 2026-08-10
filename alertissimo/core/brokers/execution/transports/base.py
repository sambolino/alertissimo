"""Physical transport protocol."""
from __future__ import annotations

from typing import Any, Mapping, Protocol

from ..models import EndpointSpec, TransportResult


class EndpointTransport(Protocol):
    name: str

    def execute(self, *, spec: EndpointSpec, params: Mapping[str, Any]) -> TransportResult: ...
