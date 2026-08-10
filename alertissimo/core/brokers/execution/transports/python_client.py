"""Transport for module functions and methods on Python client classes."""

from __future__ import annotations

from importlib import import_module
from inspect import isclass
from typing import Any

from ..models import EndpointSpec


class PythonClientTransport:
    def execute(self, spec: EndpointSpec, params: dict[str, Any], headers: dict[str, Any] | None = None) -> Any:
        callable_object = self._resolve_callable(spec.path)
        return callable_object(**params)

    @staticmethod
    def _resolve_callable(path: str) -> Any:
        parts = path.split(".")
        module = None
        remainder: list[str] = []
        for index in range(len(parts), 0, -1):
            try:
                module = import_module(".".join(parts[:index]))
            except ModuleNotFoundError as error:
                # Only suppress failure to import the candidate itself. Missing
                # dependencies inside a successfully located module must surface.
                candidate = ".".join(parts[:index])
                if error.name is None or not (
                    candidate == error.name or candidate.startswith(f"{error.name}.")
                ):
                    raise
            else:
                remainder = parts[index:]
                break
        if module is None or not remainder:
            raise ImportError(f"cannot resolve Python endpoint callable {path!r}")

        target: Any = module
        for index, name in enumerate(remainder):
            target = getattr(target, name)
            if isclass(target) and index < len(remainder) - 1:
                target = target()
        if not callable(target):
            raise TypeError(f"Python endpoint {path!r} is not callable")
        return target
