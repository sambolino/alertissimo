"""Registry-backed physical endpoint executor."""
from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Callable, Mapping

from alertissimo.core.portfolio import InternalExecutionId, InternalExecutionProvenance

from .errors import ParameterValidationError
from .ids import new_internal_execution_id
from .models import EndpointSpec, ExecutionResult
from .registry import EndpointRegistry
from .transports import PythonClientTransport, RestTransport

_TYPES = {
    "string": str, "boolean": bool, "integer": int, "number": (int, float),
    "dict": dict, "object": dict, "array": (list, tuple),
}


class RegistryEndpointExecutor:
    def __init__(
        self,
        registry: EndpointRegistry | None = None,
        transports: Mapping[str, Any] | None = None,
        execution_id_factory: Callable[[], InternalExecutionId] = new_internal_execution_id,
    ) -> None:
        self._registry = registry or EndpointRegistry()
        self._transports = {"rest": RestTransport(), "python_client": PythonClientTransport()}
        self._transports.update(transports or {})
        self._execution_id_factory = execution_id_factory

    @staticmethod
    def _validate(spec: EndpointSpec, params: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(params, Mapping):
            raise ParameterValidationError("params must be a mapping")
        unknown = set(params) - set(spec.params)
        if unknown:
            raise ParameterValidationError(f"unknown parameters: {', '.join(sorted(unknown))}")
        validated = dict(params)
        for name, definition in spec.params.items():
            if name not in validated and "default" in definition:
                validated[name] = definition["default"]
            if definition.get("required") and name not in validated:
                raise ParameterValidationError(f"missing required parameter: {name}")
            if name not in validated:
                continue
            expected = _TYPES.get(str(definition.get("type", "")).lower())
            value = validated[name]
            if expected and (not isinstance(value, expected) or
                             definition.get("type") == "integer" and isinstance(value, bool) or
                             definition.get("type") == "number" and isinstance(value, bool)):
                raise ParameterValidationError(f"parameter {name!r} has the wrong type")
            if "enum" in definition and value not in definition["enum"]:
                raise ParameterValidationError(f"parameter {name!r} is not an allowed value")
        return validated

    def call(self, broker: str, origin: str, endpoint: str,
             params: Mapping[str, Any] | None = None, **parameter_values: Any) -> ExecutionResult:
        """Execute one endpoint without interpreting its broker-native payload."""
        supplied = dict(params or {})
        supplied.update(parameter_values)
        spec = self._registry.resolve(broker, origin, endpoint)
        validated = self._validate(spec, supplied)
        try:
            transport = self._transports[spec.transport_kind]
        except KeyError as exc:
            raise ValueError(f"no transport registered for {spec.transport_kind!r}") from exc

        started_at = datetime.now(timezone.utc)
        timer_started = perf_counter()
        transport_result = transport.execute(spec=spec, params=validated)
        finished_at = datetime.now(timezone.utc)
        elapsed_ms = (perf_counter() - timer_started) * 1000.0

        execution_id = self._execution_id_factory()
        if not isinstance(execution_id, InternalExecutionId):
            raise TypeError("execution_id_factory must return InternalExecutionId")
        provenance = InternalExecutionProvenance(
            internal_execution_id=execution_id, broker=broker, origin=origin,
            endpoint=endpoint, params=dict(validated), status="success",
            started_at=started_at.isoformat(), finished_at=finished_at.isoformat(),
            elapsed_ms=elapsed_ms,
            transport=getattr(transport, "name", spec.transport_kind),
            method=transport_result.method or spec.method,
            url=transport_result.url or spec.url,
            sanitized_headers=(dict(transport_result.sanitized_headers)
                               if transport_result.sanitized_headers is not None else None),
            response_status_code=transport_result.status_code,
            response_content_type=transport_result.content_type,
            raw_size_bytes=transport_result.raw_size_bytes,
        )
        return ExecutionResult(payload=transport_result.payload, execution_provenance=provenance)
