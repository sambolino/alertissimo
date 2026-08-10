"""Load physical endpoint specifications from the broker registry."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .errors import EndpointNotFoundError
from .models import EndpointSpec


class EndpointRegistry:
    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root else Path(__file__).parents[1] / "registry"

    def resolve(self, broker: str, origin: str, endpoint: str) -> EndpointSpec:
        path = self.root / broker / origin / "endpoints.yaml"
        if not path.is_file():
            raise EndpointNotFoundError(f"no endpoint registry for {broker}/{origin}")
        with path.open(encoding="utf-8") as stream:
            document: dict[str, Any] = yaml.safe_load(stream) or {}
        try:
            raw = document["endpoints"][endpoint]
        except (KeyError, TypeError) as exc:
            raise EndpointNotFoundError(
                f"endpoint {broker}/{origin}/{endpoint} is not registered"
            ) from exc
        transport = raw.get("transport", {})
        kind = transport.get("kind") if isinstance(transport, dict) else transport
        if not kind:
            kind = "python_client" if str(raw.get("method", "")).lower() == "python" else "rest"
        return EndpointSpec(
            broker=document.get("broker", broker), origin=document.get("origin", origin),
            endpoint=endpoint, method=str(raw.get("method", "GET")).upper(),
            path=str(raw["path"]), baseurl=document.get("baseurl"),
            params=raw.get("params") or {}, headers=raw.get("headers") or {},
            transport_kind=kind,
        )
