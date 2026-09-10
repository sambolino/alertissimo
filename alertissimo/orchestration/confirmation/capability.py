"""Provider-independent endpoint eligibility for confirmation."""

from __future__ import annotations

import re

from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraph,
    EndpointCapability,
    semantic_record_noun_matches,
)
from alertissimo.orchestration.ir.predicates import Predicate, iter_semantic_references


_HISTORY_OPERATIONS = frozenset({"lightcurve", "lightcurve_lookup"})
_DYNAMIC_QUALIFIER = re.compile(r"^\{[^{}]+\}$")


def _prefer_collection(
    endpoints: tuple[EndpointCapability, ...],
) -> tuple[EndpointCapability, ...]:
    """Prefer batch confirmation, while retaining singular-only provider support."""

    collection = tuple(
        endpoint
        for endpoint in endpoints
        if "target_id" in endpoint.collection_binding_roles
    )
    return collection or endpoints


def _emits_object_evidence(
    graph: CapabilityGraph,
    endpoint: EndpointCapability,
) -> bool:
    return any(
        semantic_record_noun_matches(record.semantic_record_type, noun)
        for record in graph.records_for_endpoint(
            endpoint.broker, endpoint.origin, endpoint.endpoint
        )
        for noun in ("summary", "detection")
    )


def _record_parts(semantic_type: str) -> tuple[str, str | None, str | None]:
    noun, at, qualifiers = semantic_type.partition("@")
    if not at:
        return noun, None, None
    producer, colon, channel = qualifiers.partition(":")
    return noun, producer or None, (channel or None) if colon else None


def _qualifier_matches(actual: str | None, requested: str | None) -> bool:
    if requested is None:
        return True
    if actual is None:
        return False
    return actual.lower() == requested.lower() or bool(_DYNAMIC_QUALIFIER.fullmatch(actual))


def _emits_reference(
    graph: CapabilityGraph,
    endpoint: EndpointCapability,
    *,
    noun: str,
    field_path: str,
    producer: str | None,
    channel: str | None,
) -> bool:
    for record in graph.records_for_endpoint(
        endpoint.broker, endpoint.origin, endpoint.endpoint
    ):
        actual_noun, actual_producer, actual_channel = _record_parts(
            record.semantic_record_type
        )
        if actual_noun != noun:
            continue
        if field_path and field_path not in record.fields:
            continue
        if not _qualifier_matches(actual_producer, producer):
            continue
        if not _qualifier_matches(actual_channel, channel):
            continue
        return True
    return False


def _emits_predicate_evidence(
    graph: CapabilityGraph,
    endpoint: EndpointCapability,
    predicate: Predicate,
) -> bool:
    """Return whether one endpoint can materialize every predicate record selector."""

    references = tuple(iter_semantic_references(predicate))
    return bool(references) and all(
        _emits_reference(
            graph,
            endpoint,
            noun=reference.semantic_type,
            field_path=reference.field_path,
            producer=reference.producer,
            channel=reference.channel,
        )
        for reference in references
    )


def confirmation_endpoints(
    graph: CapabilityGraph,
    *,
    broker: str | None,
    origin: str | None,
    predicate: Predicate | None = None,
) -> tuple[EndpointCapability, ...]:
    """Return the best registered target-bound evidence endpoints for one source.

    Bare confirmation asks only whether the exact candidate exists, so it prefers
    explicit object lookups and otherwise accepts target-bound history/object
    evidence. Predicate confirmation is stricter: a participating endpoint must be
    able to materialize every semantic field referenced by the canonical predicate.
    Missing predicate capability is therefore not interpreted as a negative vote.

    The tiers are semantic/provider-contract driven; no broker or endpoint name is
    special-cased here.
    """

    bindable = tuple(
        endpoint
        for endpoint in graph.query_endpoints(broker=broker, origin=origin)
        if "target_id" in endpoint.binding_roles
    )

    if predicate is not None:
        compatible = tuple(
            endpoint
            for endpoint in bindable
            if _emits_predicate_evidence(graph, endpoint, predicate)
        )
        object_lookup = tuple(
            endpoint
            for endpoint in compatible
            if "object_lookup" in endpoint.operation_types
        )
        return _prefer_collection(object_lookup or compatible)

    object_lookup = tuple(
        endpoint
        for endpoint in bindable
        if "object_lookup" in endpoint.operation_types
        and _emits_object_evidence(graph, endpoint)
    )
    if object_lookup:
        return _prefer_collection(object_lookup)

    history = tuple(
        endpoint
        for endpoint in bindable
        if _HISTORY_OPERATIONS.intersection(endpoint.operation_types)
        and _emits_object_evidence(graph, endpoint)
    )
    if history:
        return _prefer_collection(history)

    return _prefer_collection(
        tuple(
            endpoint for endpoint in bindable if _emits_object_evidence(graph, endpoint)
        )
    )


__all__ = ["confirmation_endpoints"]
