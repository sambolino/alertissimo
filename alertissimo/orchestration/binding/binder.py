"""Provider-neutral application of endpoint parameter binding declarations.

IR supplies canonical semantic arguments, EndpointPlan supplies the selected
endpoint plus any predicate realization already proven by the planner, EndpointSpec
contains the physical contract, and BoundEndpointCall contains invocation params.
The binder applies decisions; it does not reinterpret semantic predicates.

Runtime values are an optional late-binding input for canonical roles whose values
only become available after earlier workflow Steps have executed. They do not
modify or get copied back into WorkflowIR.
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


def _set_param(
    params: dict[str, Any],
    physical_name: str,
    value: Any,
    *,
    endpoint_plan: EndpointPlan,
) -> None:
    if physical_name in params and params[physical_name] != value:
        raise UnsupportedParameterBindingError(
            f"conflicting bindings for {_context(endpoint_plan)} physical parameter "
            f"{physical_name!r}: {params[physical_name]!r} vs {value!r}"
        )
    params[physical_name] = value


def _step_binding_value(step: Step, role: str) -> Any:
    if role == "target_id":
        target = getattr(step, "target", None)
        return target.ids if target is not None else None
    return getattr(step, role, None)


def bind_endpoint(
    step: Step,
    endpoint_plan: EndpointPlan,
    registry: EndpointRegistry,
    *,
    runtime_values: Mapping[str, Any] | None = None,
) -> BoundEndpointCall:
    """Bind one canonical Step to one resolved physical endpoint contract.

    ``runtime_values`` supplies canonical binding-role values discovered during the
    same workflow invocation, for example ``target_id`` values obtained from an
    earlier normalized candidate search. Such values are late-bound inputs only;
    they never mutate the Step or become a second representation of semantic intent.
    """

    spec = registry.resolve(
        endpoint_plan.broker, endpoint_plan.origin, endpoint_plan.endpoint
    )

    # A reused semantic plan owns no new invocation. The planner has already
    # proven that an earlier execution of this same endpoint materializes the
    # requested semantic record. Runtime validates and performs the reuse.
    if endpoint_plan.execution_reuse_from is not None:
        if runtime_values:
            raise UnsupportedParameterBindingError(
                f"reused endpoint plan for {_context(endpoint_plan)} cannot accept "
                "independent runtime binding values"
            )
        return BoundEndpointCall(
            endpoint_plan=endpoint_plan,
            endpoint_spec=spec,
            params={},
        )

    supplied_runtime = dict(runtime_values or {})
    params: dict[str, Any] = {}

    realization = endpoint_plan.predicate_realization
    if realization is not None:
        for physical_name, value in realization.params.items():
            if physical_name not in spec.params:
                raise UnsupportedParameterBindingError(
                    f"predicate realization for {_context(endpoint_plan)} references "
                    f"undeclared physical parameter {physical_name!r}"
                )
            declaration = spec.params[physical_name] or {}
            coerced = _coerce_physical_type(
                value,
                declaration,
                endpoint_plan=endpoint_plan,
                physical_name=physical_name,
                role="semantic_predicate",
            )
            _set_param(
                params,
                physical_name,
                coerced,
                endpoint_plan=endpoint_plan,
            )

    declared_roles: list[str] = []
    for physical_name, raw_declaration in spec.params.items():
        declaration = raw_declaration or {}
        role = declaration.get("bind")
        if role is None:
            continue
        declared_roles.append(role)
        step_value = _step_binding_value(step, role)
        runtime_supplied = role in supplied_runtime
        runtime_value = supplied_runtime.get(role)
        if runtime_supplied and step_value is not None and runtime_value != step_value:
            raise UnsupportedParameterBindingError(
                f"runtime binding for {_context(endpoint_plan)} role {role!r} "
                "conflicts with explicit WorkflowIR value"
            )
        value = runtime_value if runtime_supplied else step_value
        if value is not None:
            transformed = _transform(
                value, declaration, endpoint_plan=endpoint_plan, role=role
            )
            coerced = _coerce_physical_type(
                transformed,
                declaration,
                endpoint_plan=endpoint_plan,
                physical_name=physical_name,
                role=role,
            )
            _set_param(
                params,
                physical_name,
                coerced,
                endpoint_plan=endpoint_plan,
            )

    unknown_runtime_roles = sorted(set(supplied_runtime) - set(declared_roles))
    if unknown_runtime_roles:
        raise UnsupportedParameterBindingError(
            f"runtime binding for {_context(endpoint_plan)} supplied roles not "
            f"declared by the endpoint: {unknown_runtime_roles}"
        )

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
    """Bind every statically-bindable semantic Step occurrence.

    Workflows containing candidate-output dependencies require staged orchestration,
    because their runtime role values do not exist until earlier Steps have executed
    and normalized. This helper intentionally remains the all-upfront static path.
    """

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
