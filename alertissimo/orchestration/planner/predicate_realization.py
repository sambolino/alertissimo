"""Partition semantic predicates into endpoint pushdown and residual pruning."""

from __future__ import annotations

from typing import Any

from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraph,
    EndpointCapability,
    RequestConstraintCapability,
)
from alertissimo.orchestration.ir.predicates import (
    BooleanPredicate,
    ComparisonPredicate,
    Predicate,
    PredicateLiteral,
    SemanticReference,
    and_predicates,
)
from alertissimo.orchestration.runtime.models import PredicateRealization


_INVERT_OPERATOR = {
    "=": "=",
    "!=": "!=",
    "<": ">",
    "<=": ">=",
    ">": "<",
    ">=": "<=",
}


def _constraint_lookup(
    graph: CapabilityGraph, endpoint: EndpointCapability
) -> dict[tuple[str, str], tuple[RequestConstraintCapability, ...]]:
    grouped: dict[tuple[str, str], list[RequestConstraintCapability]] = {}
    for item in graph.request_constraints_for(
        endpoint.broker, endpoint.origin, endpoint.endpoint
    ):
        grouped.setdefault((item.semantic_path, item.operator), []).append(item)
    return {key: tuple(values) for key, values in grouped.items()}


def _comparison_parts(
    predicate: ComparisonPredicate,
) -> tuple[SemanticReference, str, Any] | None:
    if isinstance(predicate.left, SemanticReference) and isinstance(
        predicate.right, PredicateLiteral
    ):
        return predicate.left, predicate.operator, predicate.right.value
    if isinstance(predicate.left, PredicateLiteral) and isinstance(
        predicate.right, SemanticReference
    ):
        return (
            predicate.right,
            _INVERT_OPERATOR[predicate.operator],
            predicate.left.value,
        )
    return None


def _single_constraint(
    lookup: dict[tuple[str, str], tuple[RequestConstraintCapability, ...]],
    semantic_path: str,
    operator: str,
) -> RequestConstraintCapability | None:
    matches = lookup.get((semantic_path, operator), ())
    return matches[0] if len(matches) == 1 else None


def _atomic_pushdown(
    predicate: Predicate,
    *,
    endpoint: EndpointCapability,
    lookup: dict[tuple[str, str], tuple[RequestConstraintCapability, ...]],
) -> PredicateRealization:
    if not isinstance(predicate, ComparisonPredicate):
        return PredicateRealization(residual=predicate)

    parts = _comparison_parts(predicate)
    if parts is None:
        return PredicateRealization(residual=predicate)
    reference, operator, value = parts

    if reference.channel is not None and reference.channel != endpoint.broker:
        return PredicateRealization(residual=predicate)

    field_constraint = _single_constraint(
        lookup, reference.ontology_path, operator
    )
    if field_constraint is None:
        return PredicateRealization(residual=predicate)

    params: dict[str, Any] = {field_constraint.parameter: value}

    # A qualified producer is part of the semantic reference. Pushdown is safe
    # only when the endpoint can express that qualifier too; otherwise applying
    # only the field condition could narrow the wrong producer's result set.
    if reference.producer is not None:
        producer_constraint = _single_constraint(
            lookup,
            f"{reference.semantic_type}.provenance.producer.name",
            "=",
        )
        if producer_constraint is None:
            return PredicateRealization(residual=predicate)
        existing = params.get(producer_constraint.parameter)
        if existing is not None and existing != reference.producer:
            return PredicateRealization(residual=predicate)
        params[producer_constraint.parameter] = reference.producer

    return PredicateRealization(pushdown=predicate, params=params)


def realize_predicate(
    predicate: Predicate,
    *,
    endpoint: EndpointCapability,
    graph: CapabilityGraph,
) -> PredicateRealization:
    """Partition one semantic predicate for one already-selected endpoint.

    The result never changes the predicate's meaning. Unsupported parts remain
    residual and can be evaluated after normalization. Partial pushdown is only
    performed across conjunctions, where executing a supported subset produces
    a safe superset for residual pruning.
    """

    lookup = _constraint_lookup(graph, endpoint)

    if not isinstance(predicate, BooleanPredicate) or predicate.operator != "and":
        return _atomic_pushdown(predicate, endpoint=endpoint, lookup=lookup)

    pushdown_parts: list[Predicate] = []
    residual_parts: list[Predicate] = []
    params: dict[str, Any] = {}

    for operand in predicate.operands:
        realization = realize_predicate(operand, endpoint=endpoint, graph=graph)
        for name, value in realization.params.items():
            if name in params and params[name] != value:
                # Combining incompatible physical values would require parameter-
                # specific algebra. Keep the whole semantic predicate residual.
                return PredicateRealization(residual=predicate)
            params[name] = value
        if realization.pushdown is not None:
            pushdown_parts.append(realization.pushdown)
        if realization.residual is not None:
            residual_parts.append(realization.residual)

    return PredicateRealization(
        pushdown=and_predicates(pushdown_parts),
        residual=and_predicates(residual_parts),
        params=params,
    )


__all__ = ["realize_predicate"]
