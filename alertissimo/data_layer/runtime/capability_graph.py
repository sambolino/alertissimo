"""Compile data-layer providers into an internal capability graph.

The graph describes both what provider responses can produce and which semantic
constraints provider request parameters can express. Request-side semantics are
always grounded in the same ontology paths used by response mappings.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from ..paths import PROVIDERS_ROOT


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
    binding_roles: tuple[str, ...] = ()
    collection_binding_roles: tuple[str, ...] = ()


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
class RequestConstraintCapability:
    """One physical server-filter parameter's exact ontology meaning."""

    broker: str
    origin: str
    endpoint: str
    parameter: str
    semantic_path: str
    operator: str


@dataclass(frozen=True)
class CapabilityGraph:
    endpoint_capabilities: tuple[EndpointCapability, ...]
    payload_capabilities: tuple[PayloadCapability, ...]
    field_mapping_capabilities: tuple[FieldMappingCapability, ...]
    transform_capabilities: tuple[TransformCapability, ...]
    semantic_record_capabilities: tuple[SemanticRecordCapability, ...]
    request_constraint_capabilities: tuple[RequestConstraintCapability, ...] = ()

    def endpoints_for(self, broker: str, origin: str) -> tuple[EndpointCapability, ...]:
        return tuple(
            item for item in self.endpoint_capabilities
            if item.broker == broker and item.origin == origin
        )

    def query_endpoints(
        self,
        *,
        broker: str | None = None,
        origin: str | None = None,
        operation_type: str | None = None,
        semantic_record_noun: str | None = None,
    ) -> tuple[EndpointCapability, ...]:
        """Return endpoints satisfying every supplied registry constraint."""
        matches = []
        for endpoint in self.endpoint_capabilities:
            if broker is not None and endpoint.broker != broker:
                continue
            if origin is not None and endpoint.origin != origin:
                continue
            if operation_type is not None and operation_type not in endpoint.operation_types:
                continue
            if semantic_record_noun is not None and not any(
                record.broker == endpoint.broker
                and record.origin == endpoint.origin
                and endpoint.endpoint in record.endpoints
                and semantic_record_noun_matches(
                    record.semantic_record_type, semantic_record_noun
                )
                for record in self.semantic_record_capabilities
            ):
                continue
            matches.append(endpoint)
        return tuple(matches)

    def query_records(
        self,
        *,
        broker: str | None = None,
        origin: str | None = None,
        semantic_record_noun: str | None = None,
    ) -> tuple[SemanticRecordCapability, ...]:
        return tuple(
            record for record in self.semantic_record_capabilities
            if (broker is None or record.broker == broker)
            and (origin is None or record.origin == origin)
            and (
                semantic_record_noun is None
                or semantic_record_noun_matches(
                    record.semantic_record_type, semantic_record_noun
                )
            )
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

    def request_constraints_for(
        self, broker: str, origin: str, endpoint: str
    ) -> tuple[RequestConstraintCapability, ...]:
        return tuple(
            item for item in self.request_constraint_capabilities
            if item.broker == broker
            and item.origin == origin
            and item.endpoint == endpoint
        )


def split_semantic_path(semantic_path: str) -> tuple[str, str]:
    record_type, separator, relative_path = semantic_path.partition(".")
    if not record_type:
        raise CapabilityGraphError("semantic path must not be empty")
    return record_type, relative_path if separator else ""


def canonical_semantic_noun(semantic_record_type: str) -> str:
    noun = semantic_record_type.partition("@")[0]
    if not noun:
        raise CapabilityGraphError("semantic record type must not be empty")
    return noun


def canonical_semantic_path(semantic_path: str) -> str:
    """Drop record qualifiers while preserving the ontology field path."""

    record_type, relative_path = split_semantic_path(semantic_path)
    noun = canonical_semantic_noun(record_type)
    return noun + (f".{relative_path}" if relative_path else "")


def semantic_record_noun_matches(semantic_record_type: str, noun: str) -> bool:
    return bool(noun) and canonical_semantic_noun(semantic_record_type) == noun


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
    """Build a deterministic graph from every data-layer provider declaration."""
    root = Path(registry_root) if registry_root is not None else PROVIDERS_ROOT
    endpoint_items: list[EndpointCapability] = []
    payload_items: list[PayloadCapability] = []
    field_items: list[FieldMappingCapability] = []
    transform_items: list[TransformCapability] = []
    request_items: list[RequestConstraintCapability] = []

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
        _load_mapping(unmapped_path)

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
                tuple(sorted({
                    declaration.get("bind")
                    for declaration in params.values()
                    if isinstance(declaration, dict)
                    and isinstance(declaration.get("bind"), str)
                })),
                tuple(sorted({
                    declaration.get("bind")
                    for declaration in params.values()
                    if isinstance(declaration, dict)
                    and isinstance(declaration.get("bind"), str)
                    and isinstance(declaration.get("binding"), dict)
                    and declaration["binding"].get("collection") is not None
                })),
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
        canonical_mapped_paths: set[str] = set()
        for semantic_path, refs in mappings.items():
            if not isinstance(semantic_path, str) or not isinstance(refs, list) or not refs:
                raise CapabilityGraphError(f"{mapping_path}: invalid mapping {semantic_path!r}")
            canonical_mapped_paths.add(canonical_semantic_path(semantic_path))
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

        request_path = mapping_path.with_name("request_mappings.yaml")
        if request_path.is_file():
            request_doc = _load_mapping(request_path)
            if request_doc.get("broker") != broker or request_doc.get("origin") != origin:
                raise CapabilityGraphError(
                    f"{request_path}: broker/origin do not match mappings.yaml"
                )
            constraints = _dict(
                request_doc.get("constraints", {}), f"{request_path}: constraints"
            )
            for endpoint, raw_parameters in constraints.items():
                if endpoint not in endpoint_defs:
                    raise CapabilityGraphError(
                        f"{request_path}: unknown endpoint {endpoint!r}"
                    )
                endpoint_spec = _dict(
                    endpoint_defs[endpoint], f"{endpoint_path}: endpoint {endpoint!r}"
                )
                endpoint_params = _dict(
                    endpoint_spec.get("params", {}),
                    f"{endpoint_path}: endpoint {endpoint!r} params",
                )
                server_filters = set(
                    _strings(
                        endpoint_spec.get("server_filters"),
                        f"{endpoint_path}: endpoint {endpoint!r} server_filters",
                    )
                )
                parameters = _dict(
                    raw_parameters, f"{request_path}: endpoint {endpoint!r}"
                )
                for parameter, raw_constraint in parameters.items():
                    if parameter not in endpoint_params:
                        raise CapabilityGraphError(
                            f"{request_path}: {endpoint}.{parameter} is not a declared parameter"
                        )
                    if parameter not in server_filters:
                        raise CapabilityGraphError(
                            f"{request_path}: {endpoint}.{parameter} is not a server filter"
                        )
                    constraint = _dict(
                        raw_constraint,
                        f"{request_path}: {endpoint}.{parameter}",
                    )
                    semantic_path = constraint.get("semantic_path")
                    operator = constraint.get("operator")
                    if not isinstance(semantic_path, str) or semantic_path not in canonical_mapped_paths:
                        raise CapabilityGraphError(
                            f"{request_path}: {endpoint}.{parameter} must reference an existing ontology mapping"
                        )
                    if operator not in {"=", "!=", "<", "<=", ">", ">="}:
                        raise CapabilityGraphError(
                            f"{request_path}: {endpoint}.{parameter} has invalid operator {operator!r}"
                        )
                    request_items.append(
                        RequestConstraintCapability(
                            broker=broker,
                            origin=origin,
                            endpoint=endpoint,
                            parameter=parameter,
                            semantic_path=semantic_path,
                            operator=operator,
                        )
                    )

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
                if transform_type is None:
                    continue
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
    request_items.sort(
        key=lambda x: (x.broker, x.origin, x.endpoint, x.parameter, x.semantic_path)
    )

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
        tuple(transform_items), record_items, tuple(request_items),
    )


__all__ = [
    "CapabilityGraph", "CapabilityGraphError", "EndpointCapability",
    "FieldMappingCapability", "PayloadCapability", "RequestConstraintCapability",
    "SemanticRecordCapability", "TransformCapability", "build_capability_graph",
    "canonical_semantic_noun", "canonical_semantic_path",
    "semantic_record_noun_matches", "split_semantic_path",
]
