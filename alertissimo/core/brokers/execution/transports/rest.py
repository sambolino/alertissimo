"""Generic REST transport driven by normalized endpoint registry contracts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..credentials import CredentialResolver
from ..models import EndpointSpec, TransportResult


SENSITIVE_HEADERS = {"authorization", "proxy-authorization", "x-api-key"}


def _sanitize_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        name: "<redacted>" if name.lower() in SENSITIVE_HEADERS else value
        for name, value in headers.items()
    }


class RestTransport:
    """Execute public JSON REST endpoints without semantic payload processing."""

    name = "rest"

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        credential_resolver: CredentialResolver | None = None,
    ):
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.timeout = timeout
        self.credential_resolver = credential_resolver

    def execute(
        self,
        *,
        spec: EndpointSpec,
        params: dict[str, Any],
    ) -> TransportResult:
        if spec.url is None:
            raise ValueError(
                f"REST endpoint {spec.broker}/{spec.origin}/{spec.name} has no URL"
            )
        method = (spec.method or "GET").upper()
        if method not in {"GET", "POST"}:
            raise ValueError(f"unsupported REST method {method!r}")

        encoded_params = urlencode(params, doseq=True)
        url = spec.url
        body: bytes | None = None
        headers = {
            "Accept": "application/json",
            "User-Agent": "Alertissimo/0.1",
        }
        if self.credential_resolver is not None:
            headers.update(self.credential_resolver.resolve(
                broker=spec.broker,
                origin=spec.origin,
                endpoint=spec.name,
            ))
        if method == "GET" and encoded_params:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{encoded_params}"
        elif method == "POST":
            body = encoded_params.encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                status_code = getattr(response, "status", response.getcode())
                response_url = response.geturl()
                content_type = response.headers.get("Content-Type")
        except HTTPError as exc:
            raise RuntimeError(
                f"HTTP {exc.code} from {spec.broker}/{spec.origin}/{spec.name}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(
                f"cannot reach {spec.broker}/{spec.origin}/{spec.name}: {exc.reason}"
            ) from exc

        media_type = (content_type or "").partition(";")[0].strip().lower()
        if media_type == "application/json" or media_type.endswith("+json"):
            try:
                payload: Any = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"invalid JSON from {spec.broker}/{spec.origin}/{spec.name}"
                ) from exc
        elif media_type.startswith("text/"):
            payload = raw.decode("utf-8")
        else:
            payload = raw

        return TransportResult(
            payload=payload,
            method=method,
            url=response_url,
            status_code=status_code,
            content_type=content_type,
            sanitized_headers=_sanitize_headers(headers),
            raw_size_bytes=len(raw),
        )


__all__ = ["RestTransport"]
