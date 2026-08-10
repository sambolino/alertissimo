"""Registry-backed endpoint dispatcher."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Callable, Mapping, Protocol

from alertissimo.core.portfolio import InternalExecutionId, InternalExecutionProvenance

from .ids import new_internal_execution_id

from .errors import (
    ExecutionError,
    ParameterValidationError,
    TransportExecutionError,
    TransportNotConfiguredError,
)
from .models import ExecutionResult
from .registry import EndpointRegistry
from .transports.base import EndpointTransport


class EndpointExecutor(Protocol):
    def call(
        self,
        *,
        broker: str,
        origin: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        ...


def _matches_declared_type(value: Any, declared_type: Any) -> bool:
    if not isinstance(declared_type, str):
        return True
    type_name = declared_type.lower()
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name in {"dict", "object"}:
        return isinstance(value, dict)
    # Domain types such as SkyCoord, Angle and file are validated by transports.
    return True


def _validate_params(spec: Any, supplied: Mapping[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(supplied) - set(spec.params))
    if unknown:
        raise ParameterValidationError(
            f"{spec.broker}/{spec.origin}/{spec.name}: unknown parameter(s): "
            f"{', '.join(unknown)}"
        )

    validated: dict[str, Any] = {}
    missing: list[str] = []
    for name, raw_definition in spec.params.items():
        definition = dict(raw_definition)
        if name in supplied:
            value = supplied[name]
        elif "default" in definition:
            value = deepcopy(definition["default"])
        elif definition.get("required", False):
            missing.append(name)
            continue
        else:
            continue

        if not _matches_declared_type(value, definition.get("type")):
            raise ParameterValidationError(
                f"{spec.broker}/{spec.origin}/{spec.name}: parameter {name!r} "
                f"must have type {definition.get('type')!r}"
            )
        choices = definition.get("enum")
        if choices is not None and value not in choices:
            raise ParameterValidationError(
                f"{spec.broker}/{spec.origin}/{spec.name}: parameter {name!r} "
                f"must be one of {choices!r}"
            )
        validated[name] = value

    if missing:
        raise ParameterValidationError(
            f"{spec.broker}/{spec.origin}/{spec.name}: missing required parameter(s): "
            f"{', '.join(sorted(missing))}"
        )
    validated.update(deepcopy(dict(spec.fixed_params)))
    return validated


class RegistryEndpointExecutor:
    """Resolve, validate, dispatch and describe one physical endpoint call."""

    def __init__(
        self,
        registry: EndpointRegistry,
        transports: Mapping[str, EndpointTransport],
        *,
        execution_id_factory: Callable[[], InternalExecutionId] = new_internal_execution_id,
    ):
        self.registry = registry
        self.transports = dict(transports)
        self._execution_id_factory = execution_id_factory

    def call(
        self,
        *,
        broker: str,
        origin: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        spec = self.registry.get(broker, origin, endpoint)
        supplied = {} if params is None else params
        if not isinstance(supplied, dict):
            raise ParameterValidationError("params must be a dict or None")
        validated = _validate_params(spec, supplied)

        try:
            transport = self.transports[spec.transport_kind]
        except KeyError as exc:
            raise TransportNotConfiguredError(
                f"no transport configured for kind {spec.transport_kind!r} "
                f"({broker}/{origin}/{endpoint})"
            ) from exc

        started_at = datetime.now(timezone.utc)
        timer_started = perf_counter()
        try:
            transport_result = transport.execute(spec=spec, params=validated)
        except ExecutionError:
            raise
        except Exception as exc:
            raise TransportExecutionError(
                f"transport failed for {broker}/{origin}/{endpoint}: {exc}"
            ) from exc
        completed_at = datetime.now(timezone.utc)
        elapsed_ms = (perf_counter() - timer_started) * 1000.0

        execution_id = self._execution_id_factory()
        if not isinstance(execution_id, InternalExecutionId):
            raise TypeError("execution_id_factory must return InternalExecutionId")
        provenance = InternalExecutionProvenance(
            internal_execution_id=execution_id,
            broker=broker,
            origin=origin,
            endpoint=endpoint,
            transport=getattr(transport, "name", spec.transport_kind),
            started_at=started_at,
            completed_at=completed_at,
            elapsed_ms=elapsed_ms,
            status="success",
            method=transport_result.method or spec.method,
            url=transport_result.url or spec.url,
            params=dict(validated),
            sanitized_headers=(
                dict(transport_result.sanitized_headers)
                if transport_result.sanitized_headers is not None
                else None
            ),
            response_status_code=transport_result.status_code,
            response_content_type=transport_result.content_type,
            raw_size_bytes=transport_result.raw_size_bytes,
        )
        return ExecutionResult(
            payload=transport_result.payload,
            execution_provenance=provenance,
        )


__all__ = ["EndpointExecutor", "RegistryEndpointExecutor"]
