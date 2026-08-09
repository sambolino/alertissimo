"""Construct endpoint capabilities from normalized broker registries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class CapabilityGraphError(ValueError):
    """Raised when registry data cannot be represented in the capability graph."""


@dataclass(frozen=True)
class EndpointCapability:
    """The physical endpoint information exposed to the capability graph."""

    broker: str
    origin: str
    endpoint: str
    path: str
    method: str


def _dict(value: Any, where: str) -> dict[Any, Any]:
    if not isinstance(value, dict):
        raise CapabilityGraphError(f"{where} must be a mapping")
    return value


def endpoint_capabilities(document: Any, *, source: str = "registry") -> tuple[EndpointCapability, ...]:
    """Build capabilities for the endpoints in one normalized registry document."""
    document = _dict(document, source)
    broker = document.get("broker")
    origin = document.get("origin")
    if not isinstance(broker, str):
        raise CapabilityGraphError(f"{source}: broker is missing or is not a string")
    if not isinstance(origin, str):
        raise CapabilityGraphError(f"{source}: origin is missing or is not a string")

    endpoints = _dict(document.get("endpoints"), f"{source}: endpoints")
    result: list[EndpointCapability] = []
    for endpoint, raw_spec in endpoints.items():
        if not isinstance(endpoint, str):
            raise CapabilityGraphError(f"{source}: endpoint name is not a string")
        where = f"{source}: endpoint {endpoint!r}"
        spec = _dict(raw_spec, where)
        method = spec.get("method")
        path = spec.get("path")
        if not isinstance(method, str):
            raise CapabilityGraphError(f"{where}: method is missing or is not a string")
        if not isinstance(path, str):
            raise CapabilityGraphError(f"{where}: path is missing or is not a string")
        result.append(EndpointCapability(broker, origin, endpoint, path, method))
    return tuple(result)


def load_endpoint_capabilities(path: str | Path) -> tuple[EndpointCapability, ...]:
    """Load one normalized ``endpoints.yaml`` file."""
    path = Path(path)
    try:
        with path.open(encoding="utf-8") as stream:
            document = yaml.safe_load(stream)
    except (OSError, yaml.YAMLError) as exc:
        raise CapabilityGraphError(f"{path}: cannot read YAML: {exc}") from exc
    return endpoint_capabilities(document, source=str(path))
