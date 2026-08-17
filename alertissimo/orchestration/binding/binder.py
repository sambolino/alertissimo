"""Provider-neutral application of endpoint parameter binding declarations.

The four layers are deliberately separate: an IR Step supplies canonical
semantic arguments; EndpointPlan identifies the selected endpoint; EndpointSpec
contains its physical contract and declarative binding metadata; and
BoundEndpointCall contains invocation parameters.  The registry owns physical
naming differences, the binder owns generic application of its declarations,
and neither the IR nor planner knows provider parameter names.

Cone geometry is passed through unchanged.  The initial registry declarations
use degrees for RA/Dec and arcseconds for radius, matching the existing
orchestration cone contract; no provider-dependent unit conversion occurs here.
"""

from __future__ import annotations

from typing import Any, Mapping

from alertissimo.data_layer.execution.registry import EndpointRegistry
from alertissimo.orchestration.ir.models import Step
from alertissimo.orchestration.runtime.models import (
    EndpointPlan,
    StepRunState,
    WorkflowRun,
)

from .models import BoundEndpointCall, StepBindingResult


class ParameterBindingError(ValueError):
    """Base error for an endpoint call that cannot be bound safely."""


class MissingBoundParameterError(ParameterBindingError):
    """A required physical parameter has no bound, default, or fixed value."""


class UnsupportedParameterBindingError(ParameterBindingError):
    """Canonical intent cannot yet be represented by endpoint declarations."""


def _context(plan: EndpointPlan) -> str:
    return f"{plan.broker}/{plan.origin}/{plan.endpoint}"


def _transform(
    value: Any, declaration: Mapping[str, Any], *, endpoint_plan: EndpointPlan, role: str
) -> Any:
    binding = declaration.get("binding") or {}
    collection = binding.get("collection")
    values = value if isinstance(value, (list, tuple)) else None
    if collection is None:
        if values is not None:
            if len(values) != 1:
                raise UnsupportedParameterBindingError(
                    f"unsupported parameter binding for {_context(endpoint_plan)}: "
                    f"binding role {role!r} is singular but received cardinality {len(values)}"
                )
            return values[0]
        return value
    if collection == "csv":
        values = values if values is not None else (value,)
        max_items = binding.get("max_items")
        if max_items is not None and len(values) > max_items:
            raise UnsupportedParameterBindingError(
                f"unsupported parameter binding for {_context(endpoint_plan)}: "
                f"binding role {role!r} exceeds declared limit {max_items} "
                f"with cardinality {len(values)}"
            )
        return ",".join(str(item) for item in values)
    raise ParameterBindingError(f"unknown binding collection transform {collection!r}")


def _coerce_physical_type(
    value: Any,
    declaration: Mapping[str, Any],
    *,
    endpoint_plan: EndpointPlan,
    physical_name: str,
    role: str,
) -> Any:
    """Normalize a transformed value using only its physical declaration."""

    declared_type = declaration.get("type")
    try:
        if declared_type == "integer":
            if isinstance(value, bool):
                raise ValueError("booleans are not integer parameter values")
            converted = int(value)
            if isinstance(value, float) and not value.is_integer():
                raise ValueError("non-integral number")
            return converted
        if declared_type == "number":
            if isinstance(value, bool):
                raise ValueError("booleans are not numeric parameter values")
            return float(value)
        if declared_type == "string":
            return str(value)
        if declared_type is None:
            return value
        raise ValueError(f"unsupported declared physical type {declared_type!r}")
    except (TypeError, ValueError, OverflowError) as error:
        raise ParameterBindingError(
            f"cannot bind parameter for {_context(endpoint_plan)}: physical parameter "
            f"{physical_name!r} declares type {declared_type!r}, but binding role "
            f"{role!r} produced value {value!r}"
        ) from error


def bind_endpoint(
    step: Step, endpoint_plan: EndpointPlan, registry: EndpointRegistry
) -> BoundEndpointCall:
    """Bind one canonical Step to one resolved physical endpoint contract."""

    spec = registry.resolve(
        endpoint_plan.broker, endpoint_plan.origin, endpoint_plan.endpoint
    )
    params: dict[str, Any] = {}
    declared_roles: list[str] = []
    for physical_name, raw_declaration in spec.params.items():
        declaration = raw_declaration or {}
        role = declaration.get("bind")
        if role is None:
            continue
        declared_roles.append(role)
        value = getattr(step, role, None)
        if role == "target_id":
            target = getattr(step, "target", None)
            value = target.ids if target is not None else None
        if value is not None:
            transformed = _transform(
                value, declaration, endpoint_plan=endpoint_plan, role=role
            )
            params[physical_name] = _coerce_physical_type(
                transformed,
                declaration,
                endpoint_plan=endpoint_plan,
                physical_name=physical_name,
                role=role,
            )

    # A SQL string cannot safely populate a split selected/tables/conditions
    # contract.  It remains deferred until a generic compiler is introduced.
    if getattr(step, "op", None) == "sql_query" and "query" not in declared_roles:
        raise UnsupportedParameterBindingError(
            f"unsupported parameter binding for {_context(endpoint_plan)}: canonical "
            "query has no declarative physical query binding"
        )

    for physical_name, raw_declaration in spec.params.items():
        declaration = raw_declaration or {}
        if declaration.get("required") is not True:
            continue
        if physical_name in params or physical_name in spec.fixed_params:
            continue
        if "default" in declaration:
            continue
        role = declaration.get("bind")
        raise MissingBoundParameterError(
            f"missing required parameter for {_context(endpoint_plan)}: physical "
            f"parameter {physical_name!r}, expected binding role {role!r}"
        )

    return BoundEndpointCall(
        endpoint_plan=endpoint_plan, endpoint_spec=spec, params=params
    )


def bind_workflow_run(
    run: WorkflowRun, registry: EndpointRegistry
) -> tuple[StepBindingResult, ...]:
    """Bind every plan without flattening positional Step occurrence identity."""

    for step_run in run.steps:
        if step_run.state != StepRunState.PLANNED:
            raise ParameterBindingError(
                f"step_index {step_run.step_index} is {step_run.state.value}; "
                "binding requires planned state"
            )

    return tuple(
        StepBindingResult(
            step_index=step_run.step_index,
            bound_calls=tuple(
                bind_endpoint(run.step_at(step_run.step_index), plan, registry)
                for plan in step_run.endpoint_plans
            ),
        )
        for step_run in run.steps
    )


__all__ = [
    "MissingBoundParameterError",
    "ParameterBindingError",
    "UnsupportedParameterBindingError",
    "bind_endpoint",
    "bind_workflow_run",
]
