"""Provider-neutral request-side value transformations.

These helpers operate only on already-resolved canonical values and physical
parameter declarations. They know nothing about WorkflowIR, planning, endpoint
selection, providers, or execution state.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .astropy import angle_arcsec, skycoord_icrs_degrees


class RequestTransformError(ValueError):
    """A canonical value cannot be converted into the declared physical form."""


class UnsupportedRequestTransformError(RequestTransformError):
    """A declared request transform cannot represent the supplied cardinality."""


_REQUEST_ADAPTERS: Mapping[str, Callable[..., Any]] = {
    "alertissimo.data_layer.transforms.astropy:skycoord_icrs_degrees": (
        skycoord_icrs_degrees
    ),
    "alertissimo.data_layer.transforms.astropy:angle_arcsec": angle_arcsec,
}


def _binding(declaration: Mapping[str, Any]) -> Mapping[str, Any]:
    binding = declaration.get("binding") or {}
    if not isinstance(binding, Mapping):
        raise RequestTransformError("binding metadata must be a mapping")
    return binding


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


def apply_binding_adapter(path: str, values: Mapping[str, Any]) -> Any:
    """Apply one registered pure request transform to canonical role values."""

    adapter = load_binding_adapter(path)
    try:
        return adapter(**dict(values))
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
    "coerce_physical_type",
    "load_binding_adapter",
    "transform_collection",
]
