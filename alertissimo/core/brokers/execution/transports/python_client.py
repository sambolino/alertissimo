"""Transport for registry endpoints naming an importable Python callable."""
from __future__ import annotations

from importlib import import_module
from typing import Any, Callable, Mapping

from ..models import EndpointSpec, TransportResult


class PythonClientTransport:
    name = "python_client"

    def __init__(self, resolver: Callable[[str], Callable[..., Any]] | None = None) -> None:
        self.resolver = resolver or self._resolve

    @staticmethod
    def _resolve(path: str) -> Callable[..., Any]:
        parts = path.split(".")
        for split in range(len(parts) - 1, 0, -1):
            try:
                value: Any = import_module(".".join(parts[:split]))
            except ImportError:
                continue
            for part in parts[split:]:
                value = getattr(value, part)
            return value
        raise ImportError(f"cannot resolve Python endpoint {path!r}")

    def execute(self, *, spec: EndpointSpec, params: Mapping[str, Any]) -> TransportResult:
        return TransportResult(payload=self.resolver(spec.path)(**dict(params)), method="python")
