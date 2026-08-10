"""Transport implementations for broker endpoint execution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class EndpointSpec:
    """The transport-facing portion of a broker endpoint specification."""

    broker: str
    origin: str
    endpoint: str
    transport_kind: str
    method: str | None
    url: str | None
    params: Mapping[str, Any]


@dataclass(frozen=True)
class TransportResult:
    """Payload and request metadata returned by a transport."""

    payload: Any
    method: str
    url: str
    status_code: int | None
    content_type: str | None
    headers: Mapping[str, str]
    raw_size_bytes: int


class RestTransport:
    """Execute endpoint specifications using HTTP REST requests."""

    def execute(
        self,
        spec: EndpointSpec,
        params: Mapping[str, Any],
        headers: Mapping[str, str] | None = None,
    ) -> TransportResult:
        """Execute a REST request and return its decoded response and metadata."""

        method = (spec.method or "GET").upper()
        url = spec.url
        if url is None:
            raise ValueError("REST endpoint has no URL")

        request_headers = dict(headers or {})
        body = None

        if method in {"GET", "DELETE"}:
            query = urlencode(dict(params), doseq=True)
            if query:
                separator = "&" if "?" in url else "?"
                url = f"{url}{separator}{query}"
        else:
            body = json.dumps(dict(params)).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")

        request = Request(
            url,
            data=body,
            headers=request_headers,
            method=method,
        )

        with urlopen(request) as response:
            raw = response.read()
            content_type = response.headers.get("Content-Type")
            payload = json.loads(raw.decode("utf-8"))
            response_headers = {
                key: value
                for key, value in response.headers.items()
                if key.lower() not in {"authorization", "cookie", "set-cookie"}
            }
            return TransportResult(
                payload=payload,
                method=method,
                url=request.full_url,
                status_code=getattr(response, "status", None),
                content_type=content_type,
                headers=response_headers,
                raw_size_bytes=len(raw),
            )
