"""Provider-independent endpoint eligibility for existence confirmation."""

from __future__ import annotations

from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraph,
    EndpointCapability,
    semantic_record_noun_matches,
)


_HISTORY_OPERATIONS = frozenset({"lightcurve", "lightcurve_lookup"})


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


def confirmation_endpoints(
    graph: CapabilityGraph,
    *,
    broker: str | None,
    origin: str | None,
) -> tuple[EndpointCapability, ...]:
    """Return the best registered exact-object evidence endpoints for one source.

    Confirmation needs a target-bindable provider call whose normalized result can
    attest the current canonical object identity. Prefer explicit object lookups.
    If a provider has no target-bindable object lookup, a complete target-bound
    lightcurve/history operation is an acceptable representation because it carries
    the same object's normalized summary/detection evidence. A final semantic-
    evidence tier remains for registries whose operation naming is less specific.

    The tiers are semantic/provider-contract driven; no broker or endpoint name is
    special-cased here.
    """

    bindable = tuple(
        endpoint
        for endpoint in graph.query_endpoints(broker=broker, origin=origin)
        if "target_id" in endpoint.binding_roles
    )
    object_lookup = tuple(
        endpoint
        for endpoint in bindable
        if "object_lookup" in endpoint.operation_types
        and _emits_object_evidence(graph, endpoint)
    )
    if object_lookup:
        return object_lookup

    history = tuple(
        endpoint
        for endpoint in bindable
        if _HISTORY_OPERATIONS.intersection(endpoint.operation_types)
        and _emits_object_evidence(graph, endpoint)
    )
    if history:
        return history

    return tuple(
        endpoint for endpoint in bindable if _emits_object_evidence(graph, endpoint)
    )


__all__ = ["confirmation_endpoints"]
