"""Transport interface used by the registry endpoint dispatcher."""

from __future__ import annotations

from typing import Any, Protocol

from ..models import EndpointSpec, TransportResult


class EndpointTransport(Protocol):
    name: str

    def execute(
        self,
        *,
        spec: EndpointSpec,
        params: dict[str, Any],
    ) -> TransportResult:
        ...


__all__ = ["EndpointTransport"]
