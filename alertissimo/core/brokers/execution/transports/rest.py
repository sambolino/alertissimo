"""Small standard-library REST transport for physical broker endpoints."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..models import EndpointSpec


class RestTransport:
    def execute(self, spec: EndpointSpec, params: dict[str, Any], headers: dict[str, Any] | None = None) -> Any:
        if spec.url is None:
            raise ValueError("REST endpoints require a base URL")
        request_headers = dict(headers or {})
        data = None
        url = spec.url
        if spec.method in {"GET", "DELETE"}:
            if params:
                url = f"{url}?{urlencode(params, doseq=True)}"
        else:
            data = json.dumps(params).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        request = Request(url, data=data, headers=request_headers, method=spec.method)
        with urlopen(request) as response:  # noqa: S310 - registry controls broker URLs
            body = response.read()
            if not body:
                return None
            return json.loads(body)
