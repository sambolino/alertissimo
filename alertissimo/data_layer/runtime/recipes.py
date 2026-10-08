"""Compile provider-local call recipes; never select or execute a recipe.

IR models validate operation/path references, endpoint contracts own encoding,
and endpoint-specific mappings supply possible output evidence. The resulting
immutable declarations deliberately make no feasibility or ranking decision.
"""

from __future__ import annotations

import inspect
import math
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Annotated, Any, Mapping, get_args, get_origin

import yaml
from pydantic import BaseModel

from ..transforms.request import RequestTransformError, load_binding_adapter

if TYPE_CHECKING:
    from .capability_graph import CapabilityGraph, FieldMappingCapability


class RecipeRegistryError(ValueError):
    """A provider recipe contradicts its IR or physical registry references."""


@dataclass(frozen=True)
class StepValueSource:
    path: tuple[str, ...]


@dataclass(frozen=True)
class CallValueSource:
    call_index: int
    semantic_path: str


@dataclass(frozen=True)
class ConstantValueSource:
    value: Any


@dataclass(frozen=True)
class EncoderValueSource:
    """Named operands of an encoder already declared on the physical parameter."""

    inputs: tuple[tuple[str, StepValueSource | CallValueSource], ...]


@dataclass(frozen=True)
class RecipeParameter:
    parameter: str
    source: StepValueSource | CallValueSource | ConstantValueSource | EncoderValueSource


@dataclass(frozen=True)
class RecipeCall:
    endpoint: str
    required: bool
    params: tuple[RecipeParameter, ...]
    # Possible mapped fields, not guaranteed presence or a projection proof.
    outputs: tuple[FieldMappingCapability, ...]


@dataclass(frozen=True)
class RecipeCapability:
    broker: str
    origin: str
    op: str
    alternative_index: int
    calls: tuple[RecipeCall, ...]


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode) -> dict:
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str):
            raise RecipeRegistryError("YAML mapping keys must be strings")
        if key in result:
            raise RecipeRegistryError(f"duplicate YAML key {key!r}")
        result[key] = loader.construct_object(value_node)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping
)


def _mapping(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RecipeRegistryError(f"{where}: must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise RecipeRegistryError(f"{where}: keys must be strings")
    return value


def _keys(value: dict, allowed: set[str], required: set[str], where: str) -> None:
    unknown, missing = set(value) - allowed, required - set(value)
    if unknown or missing:
        raise RecipeRegistryError(
            f"{where}: unknown keys {sorted(unknown)}; missing keys {sorted(missing)}"
        )


def _step_models() -> dict[str, type[BaseModel]]:
    # Lazy: registries without recipes retain their current import footprint.
    from alertissimo.orchestration.ir.models import StepUnion

    union = get_args(StepUnion)[0]
    return {
        op: model
        for model in get_args(union)
        for op in get_args(model.model_fields["op"].annotation)
    }


def _model_types(annotation: Any) -> tuple[type[BaseModel], ...]:
    if get_origin(annotation) is Annotated:
        return _model_types(get_args(annotation)[0])
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return (annotation,)
    # Only optional model fields are traversable; collections/dicts are not.
    args = get_args(annotation)
    if type(None) in args:
        return tuple(
            model for arg in args if arg is not type(None)
            for model in _model_types(arg)
        )
    return ()


def _step_source(value: str, model: type[BaseModel], where: str) -> StepValueSource:
    prefix, separator, relative = value.partition(".")
    path = tuple(relative.split("."))
    if prefix != "step" or not separator or any(not part.isidentifier() for part in path):
        raise RecipeRegistryError(f"{where}: expected a direct step field path")
    current = model
    for index, part in enumerate(path):
        field = current.model_fields.get(part)
        if field is None:
            raise RecipeRegistryError(f"{where}: unknown IR field {value!r}")
        if index < len(path) - 1:
            models = _model_types(field.annotation)
            if len(models) != 1:
                raise RecipeRegistryError(f"{where}: IR path cannot traverse {part!r}")
            current = models[0]
    return StepValueSource(path)


def _source(
    value: Any, model: type[BaseModel], calls: list[RecipeCall], where: str
) -> StepValueSource | CallValueSource:
    if isinstance(value, str):
        return _step_source(value, model, where)
    reference = _mapping(value, where)
    _keys(reference, {"call", "path"}, {"call", "path"}, where)
    index, path = reference["call"], reference["path"]
    if type(index) is not int or not 0 <= index < len(calls):
        raise RecipeRegistryError(f"{where}: call must reference an earlier call")
    if path != "summary.identity.object_id":
        raise RecipeRegistryError(f"{where}: only summary.identity.object_id dependencies are supported")
    if not any(
        item.semantic_record_type.partition("@")[0] == "summary"
        and item.relative_field_path == "identity.object_id"
        for item in calls[index].outputs
    ):
        raise RecipeRegistryError(f"{where}: earlier call does not map {path!r}")
    return CallValueSource(index, path)


def _encoder(declaration: dict, where: str) -> tuple[tuple[str, ...], str | None]:
    binding = _mapping(declaration.get("binding") or {}, f"{where} binding")
    roles = binding.get("roles")
    direct = declaration.get("bind")
    if roles is not None:
        if (
            direct is not None or not isinstance(roles, list) or not roles
            or any(not isinstance(role, str) or not role for role in roles)
            or len(set(roles)) != len(roles)
        ):
            raise RecipeRegistryError(f"{where}: invalid encoder roles")
        roles = tuple(roles)
    else:
        if direct is not None and (not isinstance(direct, str) or not direct):
            raise RecipeRegistryError(f"{where}: invalid bind role")
        roles = (direct,) if direct is not None else ()
    adapter = binding.get("adapter")
    if len(roles) > 1 and adapter is None:
        raise RecipeRegistryError(f"{where}: multiple operands require an adapter")
    collection = binding.get("collection")
    if collection not in (None, "csv", "adapter"):
        raise RecipeRegistryError(f"{where}: unsupported collection encoding")
    if collection == "adapter" and adapter is None:
        raise RecipeRegistryError(f"{where}: adapter collection requires an adapter")
    limit = binding.get("max_items")
    if limit is not None and (type(limit) is not int or limit <= 0):
        raise RecipeRegistryError(f"{where}: max_items must be a positive integer")
    if adapter is not None:
        options = _mapping(binding.get("adapter_options", {}), f"{where} adapter_options")
        if not isinstance(adapter, str) or set(roles).intersection(options):
            raise RecipeRegistryError(f"{where}: invalid adapter operands/options")
        try:
            function = load_binding_adapter(adapter)
            inspect.signature(function).bind(**dict.fromkeys(roles), **options)
        except (RequestTransformError, TypeError, ValueError) as exc:
            raise RecipeRegistryError(f"{where}: incompatible encoder: {exc}") from exc
    return roles, adapter


def _constant(value: Any, declaration: dict, where: str) -> ConstantValueSource:
    """Validate an already-physical constant without invoking a value encoder."""
    kind = declaration.get("type")
    expected = {
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: type(item) is int,
        "number": lambda item: type(item) is int or (type(item) is float and math.isfinite(item)),
        "boolean": lambda item: type(item) is bool,
        "dict": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
    }
    if kind is not None and (
        not isinstance(kind, str) or kind not in expected or not expected[kind](value)
    ):
        raise RecipeRegistryError(f"{where}: constant does not match physical type {kind!r}")
    if "enum" in declaration:
        enum = declaration["enum"]
        if not isinstance(enum, list) or value not in enum:
            raise RecipeRegistryError(f"{where}: constant is outside the parameter enum")
    return ConstantValueSource(_freeze_literal(value, where))


def _freeze_literal(value: Any, where: str) -> Any:
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, list):
        return tuple(_freeze_literal(item, where) for item in value)
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return MappingProxyType({
            key: _freeze_literal(item, where) for key, item in value.items()
        })
    raise RecipeRegistryError(f"{where}: constants must be finite JSON-compatible values")


def _parameter(
    name: str, raw: Any, declaration: dict, model: type[BaseModel],
    calls: list[RecipeCall], where: str,
) -> RecipeParameter:
    assignment = _mapping(raw, where)
    if set(assignment) not in ({"from"}, {"value"}):
        raise RecipeRegistryError(f"{where}: specify exactly one of from or value")
    roles, adapter = _encoder(declaration, where)
    if "value" in assignment:
        return RecipeParameter(name, _constant(assignment["value"], declaration, where))
    value = assignment["from"]
    if isinstance(value, dict) and not set(value).intersection({"call", "path"}):
        if adapter is None or set(value) != set(roles):
            raise RecipeRegistryError(f"{where}: encoder inputs must match declared operands")
        source = EncoderValueSource(tuple(
            (role, _source(value[role], model, calls, where)) for role in roles
        ))
    else:
        if len(roles) > 1:
            raise RecipeRegistryError(f"{where}: composite encoder requires named inputs")
        source = _source(value, model, calls, where)
    sources = (
        tuple(item for _, item in source.inputs)
        if isinstance(source, EncoderValueSource) else (source,)
    )
    dependencies = {item.call_index for item in sources if isinstance(item, CallValueSource)}
    if dependencies and (roles != ("target_id",) or isinstance(source, EncoderValueSource)):
        raise RecipeRegistryError(f"{where}: candidate dependency requires a target_id parameter")
    return RecipeParameter(name, source)


def load_provider_recipes(
    path: Path, graph: CapabilityGraph, endpoint_defs: Mapping[str, Any],
    *, broker: str, origin: str,
    transport_defaults: Mapping[str, Any] | None = None,
) -> tuple[RecipeCapability, ...]:
    """Load optional recipes against existing compiled provider evidence."""
    try:
        with path.open(encoding="utf-8") as stream:
            document = _mapping(yaml.load(stream, Loader=_UniqueKeyLoader), str(path))
        _keys(
            document, {"broker", "origin", "description", "recipes"},
            {"broker", "origin", "recipes"}, str(path),
        )
        if document["broker"] != broker or document["origin"] != origin:
            raise RecipeRegistryError("broker/origin do not match provider contracts")
        if "description" in document and not isinstance(document["description"], str):
            raise RecipeRegistryError("description must be a string")
        recipes = _mapping(document["recipes"], "recipes")
        defaults = _mapping(transport_defaults or {}, "transport_defaults")
        models = _step_models()
        compiled = []
        for op, alternatives in sorted(recipes.items()):
            if op not in models:
                raise RecipeRegistryError(f"unknown IR operation {op!r}")
            if not isinstance(alternatives, list) or not alternatives:
                raise RecipeRegistryError(f"recipes.{op}: alternatives must be a non-empty list")
            for alternative_index, raw_recipe in enumerate(alternatives):
                where = f"recipes.{op}[{alternative_index}]"
                recipe = _mapping(raw_recipe, where)
                _keys(recipe, {"calls"}, {"calls"}, where)
                raw_calls = recipe["calls"]
                if not isinstance(raw_calls, list) or not raw_calls:
                    raise RecipeRegistryError(f"{where}: calls must be a non-empty list")
                calls: list[RecipeCall] = []
                for index, raw_call in enumerate(raw_calls):
                    call_where = f"{where}.calls[{index}]"
                    call = _mapping(raw_call, call_where)
                    _keys(
                        call, {"endpoint", "required", "params"},
                        {"endpoint"}, call_where,
                    )
                    endpoint, required = call["endpoint"], call.get("required", True)
                    if not isinstance(endpoint, str) or endpoint not in endpoint_defs:
                        raise RecipeRegistryError(f"{call_where}: unknown endpoint {endpoint!r}")
                    if type(required) is not bool:
                        raise RecipeRegistryError(f"{call_where}: required must be boolean")
                    spec = _mapping(endpoint_defs[endpoint], call_where)
                    declarations = _mapping(spec.get("params", {}), call_where)
                    params = _mapping(call.get("params", {}), call_where)
                    transport = _mapping(spec.get("transport", {}), call_where)
                    fixed = {
                        **_mapping(defaults.get("fixed_params", {}), call_where),
                        **_mapping(transport.get("fixed_params", {}), call_where),
                    }
                    assignments = []
                    dependencies = set()
                    for name, raw in params.items():
                        if name not in declarations:
                            raise RecipeRegistryError(f"{call_where}: unknown parameter {name!r}")
                        if name in fixed and (
                            not isinstance(raw, dict) or set(raw) != {"value"}
                            or raw["value"] != fixed[name]
                        ):
                            raise RecipeRegistryError(f"{call_where}: assignment conflicts with fixed parameter {name!r}")
                        assignment = _parameter(
                            name, raw, _mapping(declarations[name], call_where),
                            models[op], calls, f"{call_where}.params.{name}",
                        )
                        assignments.append(assignment)
                        if isinstance(assignment.source, CallValueSource):
                            dependencies.add(assignment.source.call_index)
                    if len(dependencies) > 1:
                        raise RecipeRegistryError(f"{call_where}: only one candidate owner is supported")
                    if required and any(not calls[owner].required for owner in dependencies):
                        raise RecipeRegistryError(f"{call_where}: required call depends on an optional call")
                    for name, declaration in declarations.items():
                        declaration = _mapping(declaration, call_where)
                        if (
                            declaration.get("required")
                            and declaration.get("default") is None
                            and name not in params and name not in fixed
                        ):
                            raise RecipeRegistryError(f"{call_where}: required parameter {name!r} has no assignment/default")
                    calls.append(RecipeCall(
                        endpoint, required, tuple(assignments),
                        graph.fields_for_endpoint(broker, origin, endpoint),
                    ))
                if not any(call.required for call in calls):
                    raise RecipeRegistryError(f"{where}: recipe must contain a required call")
                compiled.append(RecipeCapability(
                    broker, origin, op, alternative_index, tuple(calls),
                ))
        return tuple(compiled)
    except (OSError, yaml.YAMLError, RecipeRegistryError) as exc:
        raise RecipeRegistryError(f"{path}: {exc}") from exc


__all__ = [
    "CallValueSource", "ConstantValueSource", "EncoderValueSource", "RecipeCall",
    "RecipeCapability", "RecipeParameter", "RecipeRegistryError", "StepValueSource",
    "load_provider_recipes",
]
