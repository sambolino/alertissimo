"""Compile normalized broker registries into an internal capability graph.

The objects in this module describe what registry contracts can produce.  They
do not call endpoints or construct portfolio records.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


class CapabilityGraphError(ValueError):
    """Raised when registry files cannot form a consistent capability graph."""


@dataclass(frozen=True)
class EndpointCapability:
    broker: str
    origin: str
    endpoint: str
    path: str
    method: str
    operation_types: tuple[str, ...]
    params: tuple[str, ...]
    server_filters: tuple[str, ...]
    projection_param: str | None
    supports_projection: bool
    output_type: str | None


@dataclass(frozen=True)
class PayloadCapability:
    broker: str
    origin: str
    payload_key: str
    endpoint: str
    path: str


@dataclass(frozen=True)
class FieldMappingCapability:
    broker: str
    origin: str
    semantic_path: str
    semantic_record_type: str
    relative_field_path: str
    payload_key: str
    raw_field: str
    raw_ref: str
    endpoint: str
    payload_path: str


@dataclass(frozen=True)
class TransformCapability:
    broker: str
    origin: str
    semantic_path: str
    raw_ref: str
    transform_type: str
    transform_map: Mapping[Any, Any] | None


@dataclass(frozen=True)
class SemanticRecordCapability:
    broker: str
    origin: str
    semantic_record_type: str
    endpoints: tuple[str, ...]
    fields: tuple[str, ...]


@dataclass(frozen=True)
class CapabilityGraph:
    endpoint_capabilities: tuple[EndpointCapability, ...]
    payload_capabilities: tuple[PayloadCapability, ...]
    field_mapping_capabilities: tuple[FieldMappingCapability, ...]
    transform_capabilities: tuple[TransformCapability, ...]
    semantic_record_capabilities: tuple[SemanticRecordCapability, ...]

    def endpoints_for(self, broker: str, origin: str) -> tuple[EndpointCapability, ...]:
        return tuple(
            item for item in self.endpoint_capabilities
            if item.broker == broker and item.origin == origin
        )

    def fields_for_record(self, semantic_record_type: str) -> tuple[FieldMappingCapability, ...]:
        return tuple(
            item for item in self.field_mapping_capabilities
            if item.semantic_record_type == semantic_record_type
        )

    def records_for_endpoint(
        self, broker: str, origin: str, endpoint: str
    ) -> tuple[SemanticRecordCapability, ...]:
        return tuple(
            item for item in self.semantic_record_capabilities
            if item.broker == broker
            and item.origin == origin
            and endpoint in item.endpoints
        )

    def transforms_for(
        self, semantic_path: str, raw_ref: str | None = None
    ) -> tuple[TransformCapability, ...]:
        return tuple(
            item for item in self.transform_capabilities
            if item.semantic_path == semantic_path
            and (raw_ref is None or item.raw_ref == raw_ref)
        )


def split_semantic_path(semantic_path: str) -> tuple[str, str]:
    """Split a catalog-shaped path at its first dot without binding placeholders."""
    record_type, separator, relative_path = semantic_path.partition(".")
    if not record_type:
        raise CapabilityGraphError("semantic path must not be empty")
    return record_type, relative_path if separator else ""


def _load_mapping(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as stream:
            value = yaml.safe_load(stream)
    except (OSError, yaml.YAMLError) as exc:
        raise CapabilityGraphError(f"{path}: cannot read YAML: {exc}") from exc
    if not isinstance(value, dict):
        raise CapabilityGraphError(f"{path}: document must be a mapping")
    return value


def _dict(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CapabilityGraphError(f"{where} must be a mapping")
    return value


def _strings(value: Any, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise CapabilityGraphError(f"{where} must be a list of strings")
    return tuple(sorted(value))


def build_capability_graph(registry_root: Path | str | None = None) -> CapabilityGraph:
    """Build a deterministic graph from every normalized broker/origin registry."""
    root = Path(registry_root) if registry_root is not None else Path(__file__).parents[1] / "providers"
    endpoint_items: list[EndpointCapability] = []
    payload_items: list[PayloadCapability] = []
    field_items: list[FieldMappingCapability] = []
    transform_items: list[TransformCapability] = []

    mapping_paths = sorted(root.glob("*/*/mappings.yaml"))
    if not mapping_paths:
        raise CapabilityGraphError(f"{root}: no normalized mappings.yaml files found")

    for mapping_path in mapping_paths:
        endpoint_path = mapping_path.with_name("endpoints.yaml")
        unmapped_path = mapping_path.with_name("unmapped_fields.yaml")
        if not endpoint_path.is_file() or not unmapped_path.is_file():
            raise CapabilityGraphError(
                f"{mapping_path.parent}: endpoints.yaml and unmapped_fields.yaml are required"
            )
        mappings_doc = _load_mapping(mapping_path)
        endpoints_doc = _load_mapping(endpoint_path)
        _load_mapping(unmapped_path)  # Ensure the complete normalized registry is readable.

        broker = mappings_doc.get("broker")
        origin = mappings_doc.get("origin")
        if not isinstance(broker, str) or not isinstance(origin, str):
            raise CapabilityGraphError(f"{mapping_path}: broker and origin must be strings")
        if endpoints_doc.get("broker") != broker or endpoints_doc.get("origin") != origin:
            raise CapabilityGraphError(f"{endpoint_path}: broker/origin do not match mappings.yaml")

        endpoint_defs = _dict(endpoints_doc.get("endpoints"), f"{endpoint_path}: endpoints")
        for endpoint, raw_spec in endpoint_defs.items():
            if not isinstance(endpoint, str):
                raise CapabilityGraphError(f"{endpoint_path}: endpoint names must be strings")
            spec = _dict(raw_spec, f"{endpoint_path}: endpoint {endpoint!r}")
            transport = spec.get("transport", {})
            transport = _dict(transport, f"{endpoint_path}: endpoint {endpoint!r} transport")
            method = spec.get("method", transport.get("method", ""))
            path = spec.get("path", transport.get("method", endpoint))
            if not isinstance(method, str) or not isinstance(path, str):
                raise CapabilityGraphError(f"{endpoint_path}: endpoint {endpoint!r} path/method must be strings")
            params = _dict(spec.get("params", {}), f"{endpoint_path}: endpoint {endpoint!r} params")
            projection = _dict(
                spec.get("projection", {}), f"{endpoint_path}: endpoint {endpoint!r} projection"
            )
            supports_projection = projection.get("supports_columns", False)
            projection_param = projection.get("param") if supports_projection else None
            if not isinstance(supports_projection, bool):
                raise CapabilityGraphError(f"{endpoint_path}: projection support must be boolean")
            if supports_projection and not isinstance(projection_param, str):
                raise CapabilityGraphError(f"{endpoint_path}: projected endpoint requires a param")
            output = _dict(spec.get("output", {}), f"{endpoint_path}: endpoint {endpoint!r} output")
            output_type = output.get("type")
            if output_type is not None and not isinstance(output_type, str):
                raise CapabilityGraphError(f"{endpoint_path}: output type must be a string")
            endpoint_items.append(EndpointCapability(
                broker, origin, endpoint, path, method,
                _strings(spec.get("operation_types"), f"{endpoint_path}: operation_types"),
                tuple(sorted(params)),
                _strings(spec.get("server_filters"), f"{endpoint_path}: server_filters"),
                projection_param, supports_projection, output_type,
            ))

        payload_defs = _dict(mappings_doc.get("payloads"), f"{mapping_path}: payloads")
        payload_lookup: dict[str, tuple[str, str]] = {}
        for payload_key, raw_spec in payload_defs.items():
            spec = _dict(raw_spec, f"{mapping_path}: payload {payload_key!r}")
            endpoint = spec.get("endpoint", payload_key)
            payload_path = spec.get("path")
            if endpoint not in endpoint_defs:
                raise CapabilityGraphError(
                    f"{mapping_path}: payload {payload_key!r} uses unknown endpoint {endpoint!r}"
                )
            if not isinstance(payload_key, str) or not isinstance(payload_path, str):
                raise CapabilityGraphError(f"{mapping_path}: payload key/path must be strings")
            payload_lookup[payload_key] = (endpoint, payload_path)
            payload_items.append(PayloadCapability(broker, origin, payload_key, endpoint, payload_path))

        mappings = _dict(mappings_doc.get("mappings"), f"{mapping_path}: mappings")
        for semantic_path, refs in mappings.items():
            if not isinstance(semantic_path, str) or not isinstance(refs, list) or not refs:
                raise CapabilityGraphError(f"{mapping_path}: invalid mapping {semantic_path!r}")
            record_type, relative_path = split_semantic_path(semantic_path)
            for raw_ref in refs:
                if not isinstance(raw_ref, str) or raw_ref.count("#") != 1:
                    raise CapabilityGraphError(
                        f"{mapping_path}: mapping ref {raw_ref!r} must be payload#field"
                    )
                payload_key, raw_field = raw_ref.split("#")
                if not payload_key or not raw_field:
                    raise CapabilityGraphError(
                        f"{mapping_path}: mapping ref {raw_ref!r} must have non-empty parts"
                    )
                if payload_key not in payload_lookup:
                    raise CapabilityGraphError(
                        f"{mapping_path}: mapping ref {raw_ref!r} uses unknown payload"
                    )
                endpoint, payload_path = payload_lookup[payload_key]
                field_items.append(FieldMappingCapability(
                    broker, origin, semantic_path, record_type, relative_path,
                    payload_key, raw_field, raw_ref, endpoint, payload_path,
                ))

        transforms = _dict(mappings_doc.get("transforms", {}), f"{mapping_path}: transforms")
        for semantic_path, raw_transforms in transforms.items():
            if semantic_path not in mappings:
                raise CapabilityGraphError(
                    f"{mapping_path}: transform path {semantic_path!r} is not mapped"
                )
            raw_transforms = _dict(raw_transforms, f"{mapping_path}: transform {semantic_path!r}")
            for raw_ref, raw_spec in raw_transforms.items():
                if raw_ref not in mappings[semantic_path]:
                    raise CapabilityGraphError(
                        f"{mapping_path}: transform ref {raw_ref!r} is not mapped under {semantic_path!r}"
                    )
                spec = _dict(raw_spec, f"{mapping_path}: transform {raw_ref!r}")
                transform_type = spec.get("type")
                transform_map = spec.get("map")
                if not isinstance(transform_type, str):
                    raise CapabilityGraphError(f"{mapping_path}: transform type must be a string")
                if transform_map is not None and not isinstance(transform_map, dict):
                    raise CapabilityGraphError(f"{mapping_path}: transform map must be a mapping")
                transform_items.append(TransformCapability(
                    broker, origin, semantic_path, raw_ref, transform_type,
                    dict(transform_map) if transform_map is not None else None,
                ))

    endpoint_items.sort(key=lambda x: (x.broker, x.origin, x.endpoint))
    payload_items.sort(key=lambda x: (x.broker, x.origin, x.payload_key, x.endpoint))
    field_items.sort(key=lambda x: (
        x.broker, x.origin, x.semantic_record_type, x.semantic_path, x.raw_ref, x.payload_key
    ))
    transform_items.sort(key=lambda x: (x.broker, x.origin, x.semantic_path, x.raw_ref))

    grouped: dict[tuple[str, str, str], tuple[set[str], set[str]]] = {}
    for field in field_items:
        endpoints, fields = grouped.setdefault(
            (field.broker, field.origin, field.semantic_record_type), (set(), set())
        )
        endpoints.add(field.endpoint)
        fields.add(field.relative_field_path)
    record_items = tuple(
        SemanticRecordCapability(broker, origin, record_type, tuple(sorted(endpoints)), tuple(sorted(fields)))
        for (broker, origin, record_type), (endpoints, fields) in sorted(grouped.items())
    )
    return CapabilityGraph(
        tuple(endpoint_items), tuple(payload_items), tuple(field_items),
        tuple(transform_items), record_items,
    )


__all__ = [
    "CapabilityGraph", "CapabilityGraphError", "EndpointCapability",
    "FieldMappingCapability", "PayloadCapability", "SemanticRecordCapability",
    "TransformCapability", "build_capability_graph", "split_semantic_path",
]
