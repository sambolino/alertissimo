"""Provider-neutral request-side value transformations.

These helpers operate only on already-resolved canonical values and physical
parameter declarations. They know nothing about WorkflowIR, planning, endpoint
selection, providers, or execution state.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import math
from typing import Any

from .astropy import angle_arcsec, skycoord_icrs_degrees
from .sql import string_membership_condition, time_window_condition, validate_time_window_options
from .temporal import time_bound, validate_time_encoding


class RequestTransformError(ValueError):
    """A canonical value cannot be converted into the declared physical form."""


class UnsupportedRequestTransformError(RequestTransformError):
    """A declared request transform cannot represent the supplied cardinality."""


def numeric_lower_bound(*, semantic_predicate: Any) -> list[float]:
    """Encode a finite numeric minimum as a one-element inclusive range.

    The predicate binding owns the >= operator. This transform only represents
    its already selected literal in a physical [minimum] array; no time scale,
    clock, provider, or semantic-field choice is inferred here.
    """
    if type(semantic_predicate) not in (int, float) or not math.isfinite(semantic_predicate):
        raise RequestTransformError("numeric lower bound requires a finite numeric literal")
    return [float(semantic_predicate)]


def object_mjd_range(*, field: str, time_context: Mapping | None = None,
                     semantic_predicate: Any = None) -> list[float]:
    """Encode a summary-date range or an explicit inclusive numeric minimum.

    Default detection membership uses only last >= start as a safe prefilter;
    required history evidence owns the upper bound and actual existence test.
    First/last modes use the corresponding closed summary-date range. This pure
    transform neither resolves a clock nor chooses an endpoint or evidence call.
    """
    if field not in ("first", "last"):
        raise RequestTransformError("object MJD range field must be first or last")
    if semantic_predicate is not None:
        if time_context is not None:
            raise RequestTransformError("encode predicate and window separately before intersection")
        return numeric_lower_bound(semantic_predicate=semantic_predicate)
    if time_context is None:
        raise RequestTransformError("object MJD range requires a time context or finite numeric literal")
    mode = time_context.get("mode", "detection")
    if mode == "detection" and field == "last":
        return [time_bound(time_context=time_context, bound="start", encoding="mjd")]
    if mode != field:
        raise RequestTransformError("object MJD range field conflicts with within mode")
    return time_bound(time_context=time_context, bound="range", encoding="mjd", mode=mode)


def time_binding_bounds(declaration: Mapping[str, Any], *, mode: str | None = None) -> frozenset[str]:
    """Validate a declared time encoder and describe its represented bounds."""
    declaration = time_context_declaration(declaration)
    binding = _binding(declaration)
    adapter, options = binding.get("adapter"), binding.get("adapter_options") or {}
    if adapter == "alertissimo.data_layer.transforms.sql:time_window_condition":
        if declaration.get("type") != "string" or mode is not None and mode not in ("detection", "first", "last"):
            raise RequestTransformError("SQL time encoding requires a string parameter and a valid mode")
        validate_time_window_options(**options)
        return frozenset({"start", "end"})
    if adapter == "alertissimo.data_layer.transforms.request:object_mjd_range":
        field = options.get("field")
        if field not in ("first", "last") or declaration.get("type") != "array":
            raise RequestTransformError("object MJD range requires an array and a first/last field")
        mode = field if mode is None else mode
        if mode == "detection" and field == "last":
            return frozenset({"start"})
        if mode != field:
            raise RequestTransformError("time encoder mode conflicts with selection mode")
        return frozenset({"start", "end"})
    if adapter != "alertissimo.data_layer.transforms.temporal:time_bound":
        raise RequestTransformError("time_context requires its declared time encoder")
    declared_mode = options.get("mode", "detection")
    validate_time_encoding(options.get("bound"), options.get("encoding"), declared_mode)
    if mode is not None and mode != declared_mode:
        raise RequestTransformError("time encoder mode conflicts with selection mode")
    bound = options["bound"]
    return frozenset({"start", "end"} if bound == "range" else {bound})


def intersect_numeric_ranges(left: Any, right: Any) -> list[float]:
    """Intersect inclusive [minimum] / [minimum, maximum] physical ranges.

    Preserve an empty intersection as a contradictory bounded range. The audited
    endpoint applies both comparisons, so no records can satisfy it; do not widen
    it, drop a bound, or send an infinity/None sentinel to the provider.
    """
    for value in (left, right):
        if (not isinstance(value, (list, tuple)) or len(value) not in (1, 2)
            or any(type(item) not in (int, float) or not math.isfinite(item) for item in value)):
            raise RequestTransformError("range intersection requires finite numeric bounds")
    result = [max(left[0], right[0])]
    upper = [value[1] for value in (left, right) if len(value) == 2]
    return result + [min(upper)] if upper else result


_REQUEST_ADAPTERS: Mapping[str, Callable[..., Any]] = {
    "alertissimo.data_layer.transforms.sql:time_window_condition": time_window_condition,
    "alertissimo.data_layer.transforms.request:object_mjd_range": object_mjd_range,
    "alertissimo.data_layer.transforms.request:numeric_lower_bound": numeric_lower_bound,
    "alertissimo.data_layer.transforms.temporal:time_bound": time_bound,
    "alertissimo.data_layer.transforms.astropy:skycoord_icrs_degrees": (
        skycoord_icrs_degrees
    ),
    "alertissimo.data_layer.transforms.astropy:angle_arcsec": angle_arcsec,
    "alertissimo.data_layer.transforms.sql:string_membership_condition": (
        string_membership_condition
    ),
}


def _binding(declaration: Mapping[str, Any]) -> Mapping[str, Any]:
    binding = declaration.get("binding") or {}
    if not isinstance(binding, Mapping):
        raise RequestTransformError("binding metadata must be a mapping")
    return binding


def time_context_declaration(declaration: Mapping[str, Any]) -> Mapping[str, Any]:
    """Select an explicit whole-TimeContext encoder for a shared SQL parameter.

    Its ordinary target-ID declaration is preserved for identity-bound lookups.
    Only a compiled recipe source of step.time_context selects this alternative;
    no runtime value or text sniffing chooses an encoder.
    """
    binding = _binding(declaration)
    if "time_context" not in binding:
        return declaration
    alternate = binding["time_context"]
    if (not isinstance(alternate, Mapping)
        or set(alternate) != {"adapter", "adapter_options"}
        or alternate["adapter"] != "alertissimo.data_layer.transforms.sql:time_window_condition"
        or not isinstance(alternate["adapter_options"], Mapping)
        or declaration.get("type") != "string"
        or binding_roles(declaration) != ("target_id",)):
        raise RequestTransformError("invalid alternate SQL time_context encoder")
    return {**declaration, "bind": "time_context", "binding": dict(alternate)}


def binding_roles(declaration: Mapping[str, Any]) -> tuple[str, ...]:
    """Read ordered encoder operands without resolving their semantic sources."""

    raw_roles = _binding(declaration).get("roles")
    if raw_roles is not None:
        if (
            not isinstance(raw_roles, list)
            or not raw_roles
            or any(not isinstance(role, str) or not role for role in raw_roles)
            or len(set(raw_roles)) != len(raw_roles)
        ):
            raise RequestTransformError(
                "binding.roles must be a non-empty list of unique role names"
            )
        if declaration.get("bind") is not None:
            raise RequestTransformError(
                "physical parameter declaration cannot use both bind and binding.roles"
            )
        return tuple(raw_roles)

    role = declaration.get("bind")
    if role is None:
        return ()
    if not isinstance(role, str) or not role:
        raise RequestTransformError("bind must be a non-empty role name")
    return (role,)


def load_binding_adapter(path: str) -> Callable[..., Any]:
    """Resolve one registered generic request transform callable."""

    module_name, separator, attribute = path.partition(":")
    if not separator or not module_name or not attribute:
        raise RequestTransformError(
            "binding.adapter must use 'package.module:callable' syntax"
        )
    try:
        return _REQUEST_ADAPTERS[path]
    except KeyError as error:
        raise RequestTransformError(
            f"binding.adapter {path!r} is not a registered request transform"
        ) from error


def apply_binding_adapter(
    path: str,
    values: Mapping[str, Any],
    *,
    options: Mapping[str, Any] | None = None,
) -> Any:
    """Apply one registered pure request transform to canonical role values."""

    adapter = load_binding_adapter(path)
    try:
        return adapter(**dict(values), **dict(options or {}))
    except Exception as error:
        raise RequestTransformError(
            f"binding adapter {path!r} failed: {type(error).__name__}: {error}"
        ) from error


def transform_collection(
    value: Any,
    declaration: Mapping[str, Any],
    *,
    role: str,
) -> Any:
    """Apply generic singular/collection request representation rules."""

    binding = _binding(declaration)
    collection = binding.get("collection")
    values = value if isinstance(value, (list, tuple)) else None
    if collection is None:
        if values is not None:
            if len(values) != 1:
                raise UnsupportedRequestTransformError(
                    f"binding role {role!r} is singular but received cardinality "
                    f"{len(values)}"
                )
            return values[0]
        return value
    if collection == "csv":
        values = values if values is not None else (value,)
        max_items = binding.get("max_items")
        if max_items is not None and len(values) > max_items:
            raise UnsupportedRequestTransformError(
                f"binding role {role!r} exceeds declared limit {max_items} "
                f"with cardinality {len(values)}"
            )
        return ",".join(str(item) for item in values)
    raise RequestTransformError(f"unknown binding collection transform {collection!r}")


def coerce_physical_type(
    value: Any,
    declaration: Mapping[str, Any],
    *,
    role: str,
) -> Any:
    """Coerce a generic request value to the endpoint's declared scalar type."""

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
        if declared_type == "boolean":
            if type(value) is not bool:
                raise ValueError("boolean parameter values must be booleans")
            return value
        if declared_type == "dict":
            if not isinstance(value, Mapping):
                raise ValueError("dict parameter values must be mappings")
            return dict(value)
        if declared_type == "array":
            if not isinstance(value, (list, tuple)):
                raise ValueError("array parameter values must be collections")
            return list(value)
        if declared_type is None:
            return value
        raise ValueError(f"unsupported declared physical type {declared_type!r}")
    except (TypeError, ValueError, OverflowError) as error:
        raise RequestTransformError(
            f"declares type {declared_type!r}, but binding role {role!r} produced "
            f"value {value!r}"
        ) from error


__all__ = [
    "RequestTransformError",
    "UnsupportedRequestTransformError",
    "apply_binding_adapter",
    "binding_roles",
    "coerce_physical_type",
    "load_binding_adapter",
    "transform_collection",
]
