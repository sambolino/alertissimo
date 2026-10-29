"""Provider-neutral application of endpoint parameter binding declarations.

IR supplies canonical semantic arguments, EndpointPlan supplies the selected
endpoint plus any predicate realization already proven by the planner, EndpointSpec
contains the physical contract, and BoundEndpointCall contains invocation params.
The binder applies decisions; it does not reinterpret semantic predicates.
Recipe plans provide explicit IR source paths; endpoint role assignments remain
the fallback for plans from operations that have not migrated yet. Both paths use
the same endpoint-owned physical encoders.

Runtime values are an optional late-binding input for canonical roles whose values
only become available after earlier workflow Steps have executed. They do not
modify or get copied back into WorkflowIR.

Most physical parameters bind one canonical role directly. A registry declaration
may additionally name a pure request-side adapter, optionally over multiple
canonical roles, when a physical client requires a composite/native value. Generic
value transformation lives in the data-layer transform package; orchestration owns
only role resolution, conflicts, and endpoint-call construction.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from alertissimo.data_layer.execution.registry import EndpointRegistry
from alertissimo.data_layer.transforms.temporal import resolve_time_context, utc_instant
from alertissimo.data_layer.transforms.request import (
    RequestTransformError,
    UnsupportedRequestTransformError,
    apply_binding_adapter,
    binding_roles,
    coerce_physical_type,
    intersect_numeric_ranges,
    transform_collection,
)
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


def _binding_roles(declaration: Mapping[str, Any]) -> tuple[str, ...]:
    """Keep physical-contract failures in the binder's public error family."""

    try:
        return binding_roles(declaration)
    except RequestTransformError as error:
        raise ParameterBindingError(str(error)) from error


def _transform(
    value: Any, declaration: Mapping[str, Any], *, endpoint_plan: EndpointPlan, role: str
) -> Any:
    """Apply generic request representation transforms with orchestration context."""

    try:
        return transform_collection(value, declaration, role=role)
    except UnsupportedRequestTransformError as error:
        raise UnsupportedParameterBindingError(
            f"unsupported parameter binding for {_context(endpoint_plan)}: {error}"
        ) from error
    except RequestTransformError as error:
        raise ParameterBindingError(
            f"cannot transform parameter for {_context(endpoint_plan)}: {error}"
        ) from error


def _coerce_physical_type(
    value: Any,
    declaration: Mapping[str, Any],
    *,
    endpoint_plan: EndpointPlan,
    physical_name: str,
    role: str,
) -> Any:
    """Apply generic physical type coercion with orchestration endpoint context."""

    try:
        return coerce_physical_type(value, declaration, role=role)
    except RequestTransformError as error:
        raise ParameterBindingError(
            f"cannot bind parameter for {_context(endpoint_plan)}: physical parameter "
            f"{physical_name!r} {error}"
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


def _step_binding_value(
    step: Step,
    role: str,
    target_ids_override: tuple[str, ...] | None,
) -> Any:
    if role == "target_id":
        if target_ids_override is not None:
            return target_ids_override
        target = getattr(step, "target", None)
        return target.ids if target is not None else None
    return getattr(step, role, None)


def _role_value(
    step: Step,
    role: str,
    supplied_runtime: Mapping[str, Any],
    *,
    endpoint_plan: EndpointPlan,
    target_ids_override: tuple[str, ...] | None,
) -> Any:
    step_value = _step_binding_value(step, role, target_ids_override)
    runtime_supplied = role in supplied_runtime
    runtime_value = supplied_runtime.get(role)
    if role == "target_id" and target_ids_override is not None:
        return target_ids_override
    if runtime_supplied and step_value is not None and runtime_value != step_value:
        raise UnsupportedParameterBindingError(
            f"runtime binding for {_context(endpoint_plan)} role {role!r} "
            "conflicts with explicit WorkflowIR value"
        )
    return runtime_value if runtime_supplied else step_value


def _bind_declared_parameter(
    step: Step,
    declaration: Mapping[str, Any],
    roles: tuple[str, ...],
    supplied_runtime: Mapping[str, Any],
    *,
    endpoint_plan: EndpointPlan,
    physical_name: str,
    target_ids_override: tuple[str, ...] | None,
    reference_time: datetime | None = None,
) -> Any | None:
    """Resolve direct or adapter-backed canonical roles for one physical parameter."""

    values = {
        role: _role_value(
            step,
            role,
            supplied_runtime,
            endpoint_plan=endpoint_plan,
            target_ids_override=target_ids_override,
        )
        for role in roles
    }
    return _encode_parameter_values(
        values, declaration, endpoint_plan=endpoint_plan, physical_name=physical_name,
        reference_time=reference_time,
    )


def _encode_parameter_values(
    values: Mapping[str, Any],
    declaration: Mapping[str, Any],
    *,
    endpoint_plan: EndpointPlan,
    physical_name: str,
    reference_time: datetime | None = None,
) -> Any | None:
    """Use the same physical encoder for legacy and recipe-resolved values."""
    roles = tuple(values)
    if any(value is None for value in values.values()):
        return None
    if "time_context" in values:
        context = values["time_context"]
        try:
            resolved = resolve_time_context(
                context.model_dump() if hasattr(context, "model_dump") else context,
                reference_time,
            )
        except (ValueError, OverflowError, TypeError) as error:
            raise ParameterBindingError(f"cannot resolve time_context for {_context(endpoint_plan)}: {error}") from error
        values = {**values, "time_context": resolved}

    binding = declaration.get("binding") or {}
    adapter_path = binding.get("adapter")
    if adapter_path is not None:
        if not isinstance(adapter_path, str) or not adapter_path:
            raise ParameterBindingError("binding.adapter must be a non-empty string")
        adapter_options = binding.get("adapter_options") or {}
        if not isinstance(adapter_options, Mapping):
            raise ParameterBindingError("binding.adapter_options must be a mapping")
        try:
            return apply_binding_adapter(
                adapter_path,
                values,
                options=adapter_options,
            )
        except RequestTransformError as error:
            raise ParameterBindingError(
                f"{error} for {_context(endpoint_plan)} physical parameter "
                f"{physical_name!r}"
            ) from error

    if len(roles) != 1:
        raise UnsupportedParameterBindingError(
            f"unsupported parameter binding for {_context(endpoint_plan)}: physical "
            f"parameter {physical_name!r} composes roles {roles!r} but declares no adapter"
        )
    role = roles[0]
    transformed = _transform(
        values[role], declaration, endpoint_plan=endpoint_plan, role=role
    )
    return _coerce_physical_type(
        transformed,
        declaration,
        endpoint_plan=endpoint_plan,
        physical_name=physical_name,
        role=role,
    )


def _recipe_field_value(step: Step, path: tuple[str, ...]) -> Any:
    current: Any = step
    if not path:
        raise ParameterBindingError("recipe IR field path must not be empty")
    for part in path:
        if current is None:
            return None
        if part not in getattr(type(current), "model_fields", {}):
            raise ParameterBindingError(f"invalid recipe IR field path {path!r}")
        current = getattr(current, part)
    return current


def _bind_recipe_parameter(
    step: Step,
    declaration: Mapping[str, Any],
    source: tuple[str, ...] | dict[str, tuple[str, ...]] | str,
    supplied_runtime: Mapping[str, Any],
    *,
    endpoint_plan: EndpointPlan,
    physical_name: str,
    target_ids_override: tuple[str, ...] | None,
    reference_time: datetime | None = None,
) -> tuple[Any, tuple[str, ...]]:
    roles = _binding_roles(declaration)
    if isinstance(source, str):
        if (
            source != "target_id" or roles != (source,)
            or endpoint_plan.candidate_input_from_plan is None
        ):
            raise ParameterBindingError("recipe runtime source requires a declared candidate dependency")
        value = (
            target_ids_override if target_ids_override is not None
            else supplied_runtime.get(source)
        )
        return _encode_parameter_values(
            {source: value}, declaration,
            endpoint_plan=endpoint_plan, physical_name=physical_name,
            reference_time=reference_time,
        ), roles
    if isinstance(source, dict):
        if set(source) != set(roles) or not (declaration.get("binding") or {}).get("adapter"):
            raise ParameterBindingError("recipe encoder inputs do not match the endpoint contract")
        paths = source
    else:
        if len(roles) > 1:
            raise ParameterBindingError("composite recipe encoding requires named inputs")
        paths = {roles[0] if roles else physical_name: source}
    values = {}
    for role, path in paths.items():
        explicit = _recipe_field_value(step, path)
        if path == ("target", "ids"):
            if target_ids_override is not None:
                values[role] = target_ids_override
                continue
            explicit = tuple(explicit) if explicit is not None else None
        runtime = supplied_runtime.get(role)
        if path == ("target", "ids") and isinstance(runtime, (list, tuple)):
            runtime = tuple(runtime)
        if role in supplied_runtime and explicit is not None and runtime != explicit:
            raise UnsupportedParameterBindingError(
                f"runtime binding for {_context(endpoint_plan)} role {role!r} "
                "conflicts with its recipe IR source"
            )
        values[role] = runtime if role in supplied_runtime else explicit
    return _encode_parameter_values(
        values, declaration, endpoint_plan=endpoint_plan, physical_name=physical_name,
        reference_time=reference_time,
    ), tuple(paths)


def bind_endpoint(
    step: Step,
    endpoint_plan: EndpointPlan,
    registry: EndpointRegistry,
    *,
    runtime_values: Mapping[str, Any] | None = None,
    _target_ids_override: tuple[str, ...] | None = None,
    reference_time: datetime | None = None,
) -> BoundEndpointCall:
    """Bind one canonical Step to one resolved physical endpoint contract.

    ``runtime_values`` supplies canonical binding-role values discovered during the
    same workflow invocation, for example ``target_id`` values obtained from an
    earlier normalized candidate search. Such values are late-bound inputs only;
    they never mutate the Step or become a second representation of semantic intent.
    """

    if reference_time is not None:
        reference_time = utc_instant(reference_time)
    elif getattr(step, "time_context", None) is not None:
        reference_time = datetime.now(timezone.utc)
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
    if "time_context" in supplied_runtime:
        raise UnsupportedParameterBindingError(
            "time_context must come from WorkflowIR; supply reference_time to inject a clock"
        )
    if "semantic_predicate" in supplied_runtime:
        raise UnsupportedParameterBindingError(
            "semantic_predicate must come from the planned predicate realization"
        )
    params: dict[str, Any] = {}

    for physical_name, value in endpoint_plan.request_params.items():
        if physical_name not in spec.params:
            raise UnsupportedParameterBindingError(
                f"request parameters for {_context(endpoint_plan)} reference "
                f"undeclared physical parameter {physical_name!r}"
            )
        declaration = spec.params[physical_name] or {}
        coerced = _coerce_physical_type(
            value,
            declaration,
            endpoint_plan=endpoint_plan,
            physical_name=physical_name,
            role="planned_request",
        )
        _set_param(
            params,
            physical_name,
            coerced,
            endpoint_plan=endpoint_plan,
        )

    realization = endpoint_plan.predicate_realization
    if realization is not None:
        for physical_name, value in realization.params.items():
            if physical_name not in spec.params:
                raise UnsupportedParameterBindingError(
                    f"predicate realization for {_context(endpoint_plan)} references "
                    f"undeclared physical parameter {physical_name!r}"
                )
            declaration = spec.params[physical_name] or {}
            if (_binding_roles(declaration) == ("semantic_predicate",)
                or (declaration.get("binding") or {}).get("adapter")
                == "alertissimo.data_layer.transforms.request:object_mjd_range"):
                if value is None:
                    raise ParameterBindingError(
                        f"semantic predicate literal is missing for {_context(endpoint_plan)} "
                        f"physical parameter {physical_name!r}"
                    )
                coerced = _encode_parameter_values(
                    {"semantic_predicate": value}, declaration,
                    endpoint_plan=endpoint_plan, physical_name=physical_name,
                )
            else:
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
    recipe_sources = endpoint_plan.parameter_sources
    parameter_names = spec.params if recipe_sources is None else recipe_sources
    for physical_name in parameter_names:
        if physical_name not in spec.params:
            raise UnsupportedParameterBindingError(
                f"recipe references undeclared physical parameter {physical_name!r}"
            )
        raw_declaration = spec.params[physical_name]
        declaration = raw_declaration or {}
        if recipe_sources is None:
            roles = _binding_roles(declaration)
            if not roles:
                continue
            value = _bind_declared_parameter(
                step, declaration, roles, supplied_runtime,
                endpoint_plan=endpoint_plan, physical_name=physical_name,
                target_ids_override=_target_ids_override,
                reference_time=reference_time,
            )
        else:
            value, roles = _bind_recipe_parameter(
                step, declaration, recipe_sources[physical_name], supplied_runtime,
                endpoint_plan=endpoint_plan, physical_name=physical_name,
                target_ids_override=_target_ids_override,
                reference_time=reference_time,
            )
        declared_roles.extend(roles)
        if value is not None:
            if (realization is not None and physical_name in realization.params
                and recipe_sources is not None
                and physical_name in recipe_sources
                and (declaration.get("binding") or {}).get("adapter")
                == "alertissimo.data_layer.transforms.request:object_mjd_range"):
                try:
                    params[physical_name] = intersect_numeric_ranges(params[physical_name], value)
                except RequestTransformError as error:
                    raise ParameterBindingError(f"cannot intersect range for {_context(endpoint_plan)}: {error}") from error
                continue
            _set_param(
                params,
                physical_name,
                value,
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
        if declaration.get("default") is not None:
            continue
        roles = _binding_roles(declaration)
        expected = roles[0] if len(roles) == 1 else roles or None
        raise MissingBoundParameterError(
            f"missing required parameter for {_context(endpoint_plan)}: physical "
            f"parameter {physical_name!r}, expected binding role {expected!r}"
        )

    return BoundEndpointCall(
        endpoint_plan=endpoint_plan, endpoint_spec=spec, params=params
    )


def bind_endpoint_calls(
    step: Step,
    endpoint_plan: EndpointPlan,
    registry: EndpointRegistry,
    *,
    runtime_values: Mapping[str, Any] | None = None,
    reference_time: datetime | None = None,
) -> tuple[BoundEndpointCall, ...]:
    """Bind one plan to one or more calls according to target cardinality.

    Collection declarations remain authoritative. A declared maximum produces
    deterministic chunks; a singular declaration produces one call per target ID.
    The semantic Step and EndpointPlan stay singular while physical invocations may
    be plural.
    """

    if reference_time is not None:
        reference_time = utc_instant(reference_time)
    elif getattr(step, "time_context", None) is not None:
        reference_time = datetime.now(timezone.utc)
    spec = registry.resolve(
        endpoint_plan.broker, endpoint_plan.origin, endpoint_plan.endpoint
    )
    supplied_runtime = dict(runtime_values or {})
    target = getattr(step, "target", None)
    explicit_ids = tuple(target.ids) if target is not None else None
    runtime_ids_raw = supplied_runtime.get("target_id")
    runtime_ids = (
        tuple(runtime_ids_raw)
        if isinstance(runtime_ids_raw, (list, tuple))
        else (runtime_ids_raw,)
        if runtime_ids_raw is not None
        else None
    )
    if runtime_ids is not None and explicit_ids is not None and runtime_ids != explicit_ids:
        raise UnsupportedParameterBindingError(
            f"runtime binding for {_context(endpoint_plan)} role 'target_id' "
            "conflicts with explicit WorkflowIR value"
        )
    target_ids = runtime_ids if runtime_ids is not None else explicit_ids
    if target_ids is None or len(target_ids) <= 1:
        return (
            bind_endpoint(
                step,
                endpoint_plan,
                registry,
                runtime_values=runtime_values,
                reference_time=reference_time,
            ),
        )

    declarations = []
    for declaration in spec.params.values():
        declaration = declaration or {}
        if "target_id" in _binding_roles(declaration):
            declarations.append(declaration)
    if not declarations:
        return (
            bind_endpoint(
                step,
                endpoint_plan,
                registry,
                runtime_values=runtime_values,
                reference_time=reference_time,
            ),
        )
    if len(declarations) != 1:
        raise UnsupportedParameterBindingError(
            f"unsupported parameter binding for {_context(endpoint_plan)}: "
            "target_id must feed exactly one physical parameter"
        )

    binding = declarations[0].get("binding") or {}
    if binding.get("collection") is None:
        chunk_size = 1
    else:
        declared_max = binding.get("max_items")
        chunk_size = int(declared_max) if declared_max is not None else len(target_ids)
    if chunk_size <= 0:
        raise ParameterBindingError(
            f"invalid target collection size for {_context(endpoint_plan)}"
        )

    runtime_without_target = dict(supplied_runtime)
    runtime_without_target.pop("target_id", None)
    return tuple(
        bind_endpoint(
            step,
            endpoint_plan,
            registry,
            runtime_values=runtime_without_target,
            _target_ids_override=tuple(target_ids[index : index + chunk_size]),
            reference_time=reference_time,
        )
        for index in range(0, len(target_ids), chunk_size)
    )


def bind_workflow_run(
    run: WorkflowRun, registry: EndpointRegistry, *, reference_time: datetime | None = None,
) -> tuple[StepBindingResult, ...]:
    """Bind every statically-bindable semantic Step occurrence.

    Workflows containing candidate-output dependencies require staged orchestration,
    because their runtime role values do not exist until earlier Steps have executed
    and normalized. This helper intentionally remains the all-upfront static path.
    """

    if reference_time is not None:
        reference_time = utc_instant(reference_time)

    for step_run in run.steps:
        if step_run.state != StepRunState.PLANNED:
            raise ParameterBindingError(
                f"step_index {step_run.step_index} is {step_run.state.value}; "
                "binding requires planned state"
            )

    results = []
    for step_run in run.steps:
        calls = []
        plan_indexes = []
        step = run.step_at(step_run.step_index)
        step_reference = None
        if getattr(step, "time_context", None) is not None:
            step_reference = reference_time if reference_time is not None else datetime.now(timezone.utc)
        for plan_index, plan in enumerate(step_run.endpoint_plans):
            bound = bind_endpoint_calls(step, plan, registry, reference_time=step_reference)
            calls.extend(bound)
            plan_indexes.extend([plan_index] * len(bound))
        results.append(
            StepBindingResult(
                step_index=step_run.step_index,
                bound_calls=tuple(calls),
                plan_indexes=tuple(plan_indexes),
                reference_time=step_reference,
            )
        )
    return tuple(results)


__all__ = [
    "MissingBoundParameterError",
    "ParameterBindingError",
    "UnsupportedParameterBindingError",
    "bind_endpoint",
    "bind_endpoint_calls",
    "bind_workflow_run",
]
