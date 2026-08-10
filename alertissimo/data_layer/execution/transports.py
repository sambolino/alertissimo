"""Concrete transports.  They return metadata without interpreting payloads."""

from __future__ import annotations

import importlib
import json
from typing import Any, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import EndpointSpec, TransportResult


def _sanitized(headers: Mapping[str, str]) -> dict[str, str]:
    secret_names = {"authorization", "proxy-authorization", "x-api-key", "api-key"}
    return {key: "<redacted>" if key.lower() in secret_names else value for key, value in headers.items()}


class RestTransport:
    name = "rest"

    def execute(
        self,
        spec: EndpointSpec,
        params: Mapping[str, Any],
        headers: Mapping[str, str] | None = None,
    ) -> TransportResult:
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
        with urlopen(request) as response:  # noqa: S310 - registry URLs are trusted configuration
            raw = response.read()
            content_type = response.headers.get_content_type()
            payload = json.loads(raw) if content_type == "application/json" else raw
            return TransportResult(
                payload=payload,
                method=request.method,
                url=request.full_url,
                status_code=response.status,
                content_type=content_type,
                sanitized_headers=_sanitized(request_headers),
                raw_size_bytes=len(raw),
            )


class PythonClientTransport:
    name = "python_client"

    def execute(
        self,
        spec: EndpointSpec,
        params: Mapping[str, Any],
        headers: Mapping[str, str] | None = None,
    ) -> TransportResult:
        del headers
        module = importlib.import_module(spec.module or "")
        target: Any = getattr(module, spec.client)() if spec.client else module
        method = getattr(target, spec.client_method or "")
        return TransportResult(payload=method(**dict(params)), method="python")
