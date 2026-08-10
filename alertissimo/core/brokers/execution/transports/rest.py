"""Standard-library HTTP transport for REST endpoints."""
from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..credentials import EnvironmentCredentials, redact_headers
from ..models import EndpointSpec, TransportResult


class RestTransport:
    name = "rest"

    def __init__(self, credentials: EnvironmentCredentials | None = None, timeout: float = 30) -> None:
        self.credentials = credentials or EnvironmentCredentials()
        self.timeout = timeout

    def execute(self, *, spec: EndpointSpec, params: Mapping[str, Any]) -> TransportResult:
        headers = self.credentials.headers_for(spec.broker, spec.headers)
        method = spec.method.upper()
        url = spec.url
        if url is None:
            raise ValueError("REST endpoint has no URL")
        body = None
        if method == "GET":
            query = urlencode(params)
            if query:
                url = f"{url}{'&' if '?' in url else '?'}{query}"
        else:
            body = json.dumps(dict(params)).encode()
            headers.setdefault("Content-Type", "application/json")
        request = Request(url, data=body, headers=headers, method=method)
        with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
            raw = response.read()
            content_type = response.headers.get_content_type()
            payload = json.loads(raw) if content_type == "application/json" else raw
            return TransportResult(payload, method, url, redact_headers(headers),
                                   response.status, content_type, len(raw))
