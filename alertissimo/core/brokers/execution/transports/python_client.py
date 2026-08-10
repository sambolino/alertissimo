"""Transport for registry endpoints exposed as dotted Python callables."""

from __future__ import annotations

from importlib import import_module
from typing import Any, Callable

from ..models import EndpointSpec, TransportResult


def _resolve_callable(path: str) -> Callable[..., Any]:
    parts = path.split(".")
    for split_at in range(len(parts) - 1, 0, -1):
        module_name = ".".join(parts[:split_at])
        try:
            value: Any = import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name != module_name:
                raise
            continue
        for attribute in parts[split_at:]:
            value = getattr(value, attribute)
        if not callable(value):
            raise TypeError(f"Python endpoint {path!r} is not callable")
        return value
    raise ImportError(f"cannot resolve Python endpoint {path!r}")


class PythonClientTransport:
    """Execute a dotted Python function declared by an endpoint registry."""

    name = "python-client"

    def execute(
        self,
        *,
        spec: EndpointSpec,
        params: dict[str, Any],
    ) -> TransportResult:
        if not spec.path:
            raise ValueError(
                f"Python endpoint {spec.broker}/{spec.origin}/{spec.name} has no callable path"
            )
        function = _resolve_callable(spec.path)
        payload = function(**params)
        return TransportResult(
            payload=payload,
            method="python",
            content_type="application/x-python-object",
        )


__all__ = ["PythonClientTransport"]
