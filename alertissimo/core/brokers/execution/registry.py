"""Normalize the physical endpoint registry into executable specifications."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from .models import EndpointSpec


class EndpointRegistry:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(__file__).resolve().parents[1] / "registry"

    def resolve(self, broker: str, origin: str, endpoint: str) -> EndpointSpec:
        path = self.root / broker / origin / "endpoints.yaml"
        if not path.is_file():
            raise KeyError(f"unknown broker/origin: {broker}/{origin}")
        with path.open(encoding="utf-8") as stream:
            document = yaml.safe_load(stream) or {}
        endpoints = document.get("endpoints", {})
        if endpoint not in endpoints:
            raise KeyError(f"unknown endpoint: {broker}/{origin}/{endpoint}")

        raw = endpoints[endpoint] or {}
        defaults = document.get("transport_defaults", {}) or {}
        transport = self._merge_transport(defaults, raw.get("transport", {}) or {})

        # Older REST and Python-client registries put physical details directly
        # on the endpoint. New client registries put them below ``transport``.
        raw_method = raw.get("method")
        kind = transport.get("kind")
        if kind is None:
            kind = "python_client" if str(raw_method).lower() in {"python", "python_client"} else "rest"
        transport_kind = "python_client" if str(kind).lower() in {"python", "python_client"} else str(kind).lower()

        if transport_kind == "python_client":
            method = "python"
            callable_path = raw.get("path") or self._python_path(transport)
        else:
            method = str(raw_method or transport.get("method") or "GET").upper()
            callable_path = raw.get("path") or transport.get("path")
        if not callable_path:
            raise ValueError(f"endpoint {broker}/{origin}/{endpoint} has no executable path")

        return EndpointSpec(
            broker=str(document.get("broker", broker)),
            origin=str(document.get("origin", origin)),
            endpoint=endpoint,
            transport_kind=transport_kind,
            method=method,
            path=str(callable_path),
            baseurl=document.get("baseurl"),
            params=raw.get("params", {}) or {},
            headers=raw.get("headers", {}) or {},
            fixed_params=transport.get("fixed_params", {}) or {},
        )

    @staticmethod
    def _merge_transport(defaults: Any, endpoint: Any) -> dict[str, Any]:
        if not isinstance(defaults, Mapping) or not isinstance(endpoint, Mapping):
            raise ValueError("transport defaults and endpoint transport must be mappings")
        merged = dict(defaults)
        merged.update(endpoint)
        default_fixed = defaults.get("fixed_params", {}) or {}
        endpoint_fixed = endpoint.get("fixed_params", {}) or {}
        merged["fixed_params"] = {**default_fixed, **endpoint_fixed}
        return merged

    @staticmethod
    def _python_path(transport: Mapping[str, Any]) -> str | None:
        module = transport.get("module")
        method = transport.get("method")
        if not module or not method:
            return None
        client = transport.get("client")
        return ".".join(str(part) for part in (module, client, method) if part)
