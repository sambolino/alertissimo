"""Endpoint executor which returns raw payloads and execution provenance."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from alertissimo.core.portfolio.models import InternalExecutionId, InternalExecutionProvenance

from .models import EndpointExecutionResult, EndpointSpec
from .registry import EndpointRegistry
from .transports.python_client import PythonClientTransport
from .transports.rest import RestTransport


class EndpointExecutor:
    def __init__(self, registry: EndpointRegistry | None = None, transports: dict[str, Any] | None = None) -> None:
        self.registry = registry or EndpointRegistry()
        self.transports = {
            "python_client": PythonClientTransport(),
            "rest": RestTransport(),
            **(transports or {}),
        }

    def execute(self, broker: str, origin: str, endpoint: str, params: dict[str, Any] | None = None, headers: dict[str, Any] | None = None) -> EndpointExecutionResult:
        spec = self.registry.resolve(broker, origin, endpoint)
        validated = self._validate_params(spec, params or {})
        validated.update(dict(spec.fixed_params))
        started = self._now()
        transport = self.transports.get(spec.transport_kind)
        if transport is None:
            raise NotImplementedError(f"transport {spec.transport_kind!r} is not configured")
        payload = transport.execute(spec, validated, headers or {})
        provenance = InternalExecutionProvenance(
            internal_execution_id=InternalExecutionId(str(uuid4())),
            broker=spec.broker,
            origin=spec.origin,
            endpoint=spec.endpoint,
            params=validated,
            status="success",
            started_at=started,
            finished_at=self._now(),
        )
        return EndpointExecutionResult(payload=payload, provenance=provenance)

    @staticmethod
    def _validate_params(spec: EndpointSpec, supplied: dict[str, Any]) -> dict[str, Any]:
        unknown = supplied.keys() - spec.params.keys()
        if unknown:
            raise ValueError(f"unknown parameters: {', '.join(sorted(unknown))}")
        validated = dict(supplied)
        missing = []
        for name, contract in spec.params.items():
            if name in validated:
                continue
            if isinstance(contract, dict) and "default" in contract:
                validated[name] = contract["default"]
            elif isinstance(contract, dict) and contract.get("required") is True:
                missing.append(name)
        if missing:
            raise ValueError(f"missing required parameters: {', '.join(sorted(missing))}")
        return validated

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
