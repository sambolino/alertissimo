"""Deterministic transport for tests and documented examples."""
from __future__ import annotations

from typing import Any, Mapping

from ..models import EndpointSpec, TransportResult


class FixtureTransport:
    name = "fixture"

    def __init__(self, payload: Any, *, headers: Mapping[str, str] | None = None,
                 status_code: int = 200, content_type: str = "application/json") -> None:
        self.payload = payload
        self.headers = dict(headers or {})
        self.status_code = status_code
        self.content_type = content_type

    def execute(self, *, spec: EndpointSpec, params: Mapping[str, Any]) -> TransportResult:
        from ..credentials import redact_headers
        return TransportResult(
            payload=self.payload, method=spec.method, url=spec.url,
            sanitized_headers=redact_headers(self.headers), status_code=self.status_code,
            content_type=self.content_type,
        )
