"""Compile provider predicate-binding declarations into a generic registry.

This module describes how semantic predicate intent can be represented by
physical endpoint parameters.  The declarations live beside provider endpoint
and mapping contracts; this loader contains no provider-specific rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from ..paths import PROVIDERS_ROOT
from .capability_graph import CapabilityGraph, build_capability_graph


class PredicateBindingRegistryError(ValueError):
    """Raised when predicate-binding declarations are inconsistent."""


@dataclass(frozen=True)
class PredicateBindingCapability:
    broker: str
    origin: str
    endpoint: str
    physical_param: str
    semantic_record: str
    semantic_path: str | None
    value_from: Literal["literal", "producer"]
    operators: tuple[str, ...] = ()
    requires_producer: bool = False


@dataclass(frozen=True)
class PredicateBindingRegistry:
    capabilities: tuple[PredicateBindingCapability, ...]

    def query(
        self,
        *,
        broker: str | None = None,
        origin: str | None = None,
        endpoint: str | None = None,
        semantic_record: str | None = None,
        semantic_path: str | None = None,
        value_from: Literal["literal", "producer"] | None = None,
    ) -> tuple[PredicateBindingCapability, ...]:
        return tuple(
            item
            for item in self.capabilities
            if (broker is None or item.broker == broker)
            and (origin is None or item.origin == origin)
            and (endpoint is None or item.endpoint == endpoint)
            and (semantic_record is None or item.semantic_record == semantic_record)
            and (semantic_path is None or item.semantic_path == semantic_path)
            and (value_from is None or item.value_from == value_from)
        )


def _load_mapping(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as stream:
            value = yaml.safe_load(stream) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise PredicateBindingRegistryError(f"{path}: cannot read YAML: {exc}") from exc
    if not isinstance(value, dict):
        raise PredicateBindingRegistryError(f"{path}: document must be a mapping")
    return value


def _endpoint_capability(
    graph: CapabilityGraph,
    *,
    broker: str,
    origin: str,
    endpoint: str,
):
    matches = tuple(
        item
        for item in graph.endpoint_capabilities
        if item.broker == broker
        and item.origin == origin
        and item.endpoint == endpoint
    )
    if len(matches) != 1:
        raise PredicateBindingRegistryError(
            f"predicate binding references unknown endpoint {broker}/{origin}/{endpoint}"
        )
    return matches[0]


def build_predicate_binding_registry(
    graph: CapabilityGraph | None = None,
    registry_root: Path | str | None = None,
) -> PredicateBindingRegistry:
    """Build semantic-predicate -> physical-parameter capabilities.

    Each optional ``predicate_bindings.yaml`` file is validated against the
    normalized endpoint capability graph.  A declared physical parameter must
    exist and must already be advertised as a server filter by that endpoint.
    """

    root = Path(registry_root) if registry_root is not None else PROVIDERS_ROOT
    capability_graph = graph or build_capability_graph(root)
    items: list[PredicateBindingCapability] = []
    allowed_operators = {"=", "!=", "<", "<=", ">", ">="}

    for path in sorted(root.glob("*/*/predicate_bindings.yaml")):
        document = _load_mapping(path)
        broker = document.get("broker")
        origin = document.get("origin")
        bindings = document.get("bindings", {})
        if not isinstance(broker, str) or not isinstance(origin, str):
            raise PredicateBindingRegistryError(
                f"{path}: broker and origin must be strings"
            )
        if not isinstance(bindings, dict):
            raise PredicateBindingRegistryError(f"{path}: bindings must be a mapping")

        for endpoint, raw_parameters in bindings.items():
            if not isinstance(endpoint, str) or not isinstance(raw_parameters, dict):
                raise PredicateBindingRegistryError(
                    f"{path}: endpoint predicate bindings must be mappings"
                )
            endpoint_capability = _endpoint_capability(
                capability_graph,
                broker=broker,
                origin=origin,
                endpoint=endpoint,
            )

            for physical_param, raw_spec in raw_parameters.items():
                if not isinstance(physical_param, str) or not isinstance(raw_spec, dict):
                    raise PredicateBindingRegistryError(
                        f"{path}: predicate parameter declarations must be mappings"
                    )
                if physical_param not in endpoint_capability.params:
                    raise PredicateBindingRegistryError(
                        f"{path}: {endpoint!r} has no parameter {physical_param!r}"
                    )
                if physical_param not in endpoint_capability.server_filters:
                    raise PredicateBindingRegistryError(
                        f"{path}: {endpoint!r}/{physical_param!r} is not a server filter"
                    )

                semantic_path = raw_spec.get("semantic_path")
                semantic_record = raw_spec.get("semantic_record")
                value_from = raw_spec.get("value_from", "literal")
                operators = raw_spec.get("operators", [])
                requires_producer = raw_spec.get("requires_producer", False)

                if semantic_path is not None:
                    if not isinstance(semantic_path, str) or "." not in semantic_path:
                        raise PredicateBindingRegistryError(
                            f"{path}: semantic_path must be '<record>.<field path>'"
                        )
                    path_record = semantic_path.partition(".")[0]
                    if semantic_record is None:
                        semantic_record = path_record
                    elif semantic_record != path_record:
                        raise PredicateBindingRegistryError(
                            f"{path}: semantic_record disagrees with semantic_path"
                        )
                if not isinstance(semantic_record, str) or not semantic_record:
                    raise PredicateBindingRegistryError(
                        f"{path}: semantic_record is required"
                    )
                if value_from not in {"literal", "producer"}:
                    raise PredicateBindingRegistryError(
                        f"{path}: value_from must be 'literal' or 'producer'"
                    )
                if not isinstance(operators, list) or any(
                    not isinstance(operator, str) or operator not in allowed_operators
                    for operator in operators
                ):
                    raise PredicateBindingRegistryError(
                        f"{path}: operators must contain supported comparison operators"
                    )
                if not isinstance(requires_producer, bool):
                    raise PredicateBindingRegistryError(
                        f"{path}: requires_producer must be boolean"
                    )
                if value_from == "literal" and semantic_path is None:
                    raise PredicateBindingRegistryError(
                        f"{path}: literal predicate bindings require semantic_path"
                    )
                if value_from == "literal" and not operators:
                    raise PredicateBindingRegistryError(
                        f"{path}: literal predicate bindings require operators"
                    )
                if value_from == "producer" and operators:
                    raise PredicateBindingRegistryError(
                        f"{path}: producer bindings do not take comparison operators"
                    )

                items.append(
                    PredicateBindingCapability(
                        broker=broker.lower(),
                        origin=origin.lower(),
                        endpoint=endpoint,
                        physical_param=physical_param,
                        semantic_record=semantic_record.lower(),
                        semantic_path=(
                            semantic_path.lower() if semantic_path is not None else None
                        ),
                        value_from=value_from,
                        operators=tuple(operators),
                        requires_producer=requires_producer,
                    )
                )

    items.sort(
        key=lambda item: (
            item.broker,
            item.origin,
            item.endpoint,
            item.physical_param,
        )
    )
    return PredicateBindingRegistry(tuple(items))


__all__ = [
    "PredicateBindingCapability",
    "PredicateBindingRegistry",
    "PredicateBindingRegistryError",
    "build_predicate_binding_registry",
]
