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
from alertissimo.orchestration.runtime.models import EndpointPlan, WorkflowRun

from .models import BoundEndpointCall, StepBindingResult


class ParameterBindingError(ValueError):
    """Base error for an endpoint call that cannot be bound safely."""


class MissingBoundParameterError(ParameterBindingError):
    """A required physical parameter has no bound, default, or fixed value."""


class UnsupportedParameterBindingError(ParameterBindingError):
    """Canonical intent cannot yet be represented by endpoint declarations."""


def _context(plan: EndpointPlan) -> str:
    return f"{plan.broker}/{plan.origin}/{plan.endpoint}"


def _transform(value: Any, declaration: Mapping[str, Any]) -> Any:
    binding = declaration.get("binding") or {}
    collection = binding.get("collection")
    if collection is None:
        return value
    if collection == "csv":
        values = value if isinstance(value, (list, tuple)) else (value,)
        return ",".join(str(item) for item in values)
    raise ParameterBindingError(f"unknown binding collection transform {collection!r}")


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
        if value is not None:
            params[physical_name] = _transform(value, declaration)

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
