"""Registry-driven endpoint executor."""

from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Callable, Mapping

from alertissimo.core.portfolio import InternalExecutionId, InternalExecutionProvenance

from .ids import new_internal_execution_id
from .models import EndpointSpec, ExecutionResult, TransportResult
from .registry import EndpointRegistry
from .transports import PythonClientTransport, RestTransport


class RegistryEndpointExecutor:
    def __init__(
        self,
        registry: EndpointRegistry | None = None,
        transports: Mapping[str, Any] | None = None,
        execution_id_factory: Callable[[], InternalExecutionId] = new_internal_execution_id,
    ) -> None:
        self.registry = registry or EndpointRegistry()
        self.transports = {
            "rest": RestTransport(),
            "python_client": PythonClientTransport(),
            **dict(transports or {}),
        }
        self.execution_id_factory = execution_id_factory

    @staticmethod
    def _validated_params(
        spec: EndpointSpec, supplied: Mapping[str, Any]
    ) -> dict[str, Any]:
        unknown = set(supplied) - set(spec.params)
        if unknown:
            raise ValueError(f"unknown endpoint parameters: {', '.join(sorted(unknown))}")
        validated = dict(supplied)
        for name, contract in spec.params.items():
            contract = contract or {}
            if name not in validated and "default" in contract:
                validated[name] = contract["default"]
            if contract.get("required") is True and name not in validated:
                raise ValueError(f"missing required endpoint parameter: {name}")
        # Fixed values are executor-owned and are deliberately applied last.
        validated.update(spec.fixed_params)
        return validated

    def execute(
        self,
        broker: str,
        origin: str,
        endpoint: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> ExecutionResult:
        spec = self.registry.resolve(broker, origin, endpoint)
        validated = self._validated_params(spec, params or {})
        execution_id = self.execution_id_factory()
        started = datetime.now(timezone.utc)
        timer = perf_counter()
        transport = self.transports[spec.transport_kind]
        transport_result = (
            transport.execute(spec, validated, headers)
            if headers is not None
            else transport.execute(spec, validated)
        )
        if not isinstance(transport_result, TransportResult):
            raise TypeError("endpoint transports must return TransportResult")
        elapsed_ms = (perf_counter() - timer) * 1000
        finished = datetime.now(timezone.utc)
        provenance = InternalExecutionProvenance(
            internal_execution_id=execution_id,
            broker=spec.broker,
            origin=spec.origin,
            endpoint=spec.endpoint,
            params=dict(validated),
            status="success",
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            elapsed_ms=elapsed_ms,
            transport=getattr(transport, "name", spec.transport_kind),
            method=transport_result.method or spec.method,
            url=transport_result.url or spec.url,
            sanitized_headers=(
                dict(transport_result.sanitized_headers)
                if transport_result.sanitized_headers is not None
                else None
            ),
            response_status_code=transport_result.status_code,
            response_content_type=transport_result.content_type,
            raw_size_bytes=transport_result.raw_size_bytes,
        )
        return ExecutionResult(payload=transport_result.payload, execution_provenance=provenance)


EndpointExecutor = RegistryEndpointExecutor
