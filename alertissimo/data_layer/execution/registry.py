"""Normalization of provider endpoint declarations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urljoin

import yaml

from ..paths import PROVIDERS_ROOT
from .models import EndpointSpec


class EndpointRegistry:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else PROVIDERS_ROOT

    def resolve(self, broker: str, origin: str, endpoint: str) -> EndpointSpec:
        path = self.root / broker / origin / "endpoints.yaml"
        with path.open(encoding="utf-8") as stream:
            document = yaml.safe_load(stream) or {}
        try:
            endpoint_data = document["endpoints"][endpoint]
        except KeyError as error:
            raise KeyError(f"unknown endpoint {broker}/{origin}/{endpoint}") from error

        defaults = dict(document.get("transport_defaults") or {})
        explicit = endpoint_data.get("transport")
        if isinstance(explicit, str):
            explicit = {"kind": explicit}
        transport = {**defaults, **dict(explicit or {})}
        default_fixed = dict(defaults.get("fixed_params") or {})
        transport["fixed_params"] = {
            **default_fixed,
            **dict((explicit or {}).get("fixed_params") or {}),
        }

        # Older registries describe REST/Python calls with top-level path/method.
        top_method = endpoint_data.get("method")
        top_path = endpoint_data.get("path")
        kind = transport.get("kind")
        if not kind:
            kind = "python" if str(top_method).lower() == "python" else "rest"
        kind = "python_client" if kind in {"python", "python_client"} else kind

        module = transport.get("module")
        client = transport.get("client")
        client_method = transport.get("method")
        if kind == "python_client" and top_path and not client_method:
            dotted = str(top_path).split(".")
            module, client_method = ".".join(dotted[:-1]), dotted[-1]

        base_url = document.get("baseurl") or document.get("base_url")
        url = transport.get("url")
        if not url and top_path and kind == "rest":
            url = urljoin(f"{str(base_url).rstrip('/')}/", str(top_path).lstrip("/"))

        return EndpointSpec(
            broker=document.get("broker", broker),
            origin=document.get("origin", origin),
            endpoint=endpoint,
            transport_kind=kind,
            request_encoding=transport.get("request_encoding", "json"),
            params=endpoint_data.get("params") or {},
            fixed_params=transport["fixed_params"],
            method=transport.get("http_method") or (top_method if kind == "rest" else None),
            url=url,
            module=module,
            client=client,
            client_method=client_method,
            headers=endpoint_data.get("headers") or {},
        )
