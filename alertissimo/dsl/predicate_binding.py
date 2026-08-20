"""Declarative binding of first-pass DSL predicates to provider server filters.

This layer consumes formal expression AST nodes plus provider-owned predicate
binding declarations.  It reports exact physical parameter bindings that are
safe to push down, together with residual predicates that must remain local or
be handled by later planning.  It never selects or executes an endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from alertissimo.data_layer.runtime.capability_graph import CapabilityGraph
from alertissimo.data_layer.runtime.predicate_bindings import (
    PredicateBindingCapability,
    PredicateBindingRegistry,
    build_predicate_binding_registry,
)

from .expression import (
    BooleanExpression,
    ComparisonExpression,
    ExpressionModel,
    LiteralExpression,
    ReferenceExpression,
    parse_expression,
)
from .surface import FilterClause, RequirementClause, SurfaceScript, WhereClause
from .validation import resolve_expression_references, resolve_record_type


Scalar = str | int | float | bool


class PredicateParameterBinding(BaseModel):
    """One exact semantic-intent -> physical-parameter binding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    physical_name: str
    value: Scalar
    value_from: Literal["literal", "producer"]
    semantic_record: str
    semantic_path: str | None = None
    operator: str | None = None


class EndpointPredicateBinding(BaseModel):
    """Predicate pushdown evidence for one candidate endpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    broker: str
    origin: str
    endpoint: str
    bindings: tuple[PredicateParameterBinding, ...] = ()
    consumed_predicates: tuple[str, ...] = ()
    residual_reasons: tuple[str, ...] = ()
    total_predicates: int = 0

    @property
    def params(self) -> dict[str, Scalar]:
        return {item.physical_name: item.value for item in self.bindings}

    @property
    def complete(self) -> bool:
        return (
            self.total_predicates > 0
            and len(self.consumed_predicates) == self.total_predicates
            and not self.residual_reasons
        )


class SurfacePredicateBindingReport(BaseModel):
    """All declared endpoint pushdown possibilities for a SurfaceScript."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    endpoints: tuple[EndpointPredicateBinding, ...] = ()

    @property
    def complete_endpoints(self) -> tuple[EndpointPredicateBinding, ...]:
        return tuple(item for item in self.endpoints if item.complete)


class _SemanticPaths(Protocol):
    record_types: frozenset[str]


@dataclass(frozen=True)
class _PredicateUnit:
    expression: ExpressionModel
    label: str


_INVERT_OPERATOR = {
    "=": "=",
    "!=": "!=",
    "<": ">",
    "<=": ">=",
    ">": "<",
    ">=": "<=",
}


def _semantic_path_model() -> _SemanticPaths:
    from alertissimo.data_layer.semantic_model import SemanticPathModel

    return SemanticPathModel.from_ontology()


def _first_filter_index(surface: SurfaceScript) -> int:
    return next(
        (
            index
            for index, clause in enumerate(surface.clauses)
            if isinstance(clause, FilterClause)
        ),
        len(surface.clauses),
    )


def _flatten_conjunction(expression: ExpressionModel, label: str):
    if isinstance(expression, BooleanExpression) and expression.operator == "and":
        for operand in expression.operands:
            yield from _flatten_conjunction(operand, label)
        return
    yield _PredicateUnit(expression=expression, label=label)


def _first_pass_predicates(
    surface: SurfaceScript,
    *,
    record_types: frozenset[str],
) -> tuple[_PredicateUnit, ...]:
    units: list[_PredicateUnit] = []
    first_filter = _first_filter_index(surface)

    for index, clause in enumerate(surface.clauses[:first_filter]):
        if isinstance(clause, WhereClause):
            resolved = resolve_expression_references(
                parse_expression(clause.condition), record_types
            )
            units.extend(
                _flatten_conjunction(resolved, f"where clause {index}")
            )
            continue

        if not isinstance(clause, RequirementClause) or not clause.predicates:
            continue
        noun = resolve_record_type(clause.product, record_types)
        if noun is None:
            continue
        channel = clause.via or surface.candidates.broker
        for predicate_index, predicate in enumerate(clause.predicates):
            resolved = resolve_expression_references(
                parse_expression(predicate),
                record_types,
                scoped_noun=noun,
                scoped_producer=clause.source,
                scoped_channel=channel,
            )
            units.extend(
                _flatten_conjunction(
                    resolved,
                    f"with clause {index} predicate {predicate_index}",
                )
            )

    return tuple(units)


def _comparison_parts(
    expression: ExpressionModel,
) -> tuple[ReferenceExpression, str, Scalar] | None:
    if not isinstance(expression, ComparisonExpression):
        return None
    if isinstance(expression.left, ReferenceExpression) and isinstance(
        expression.right, LiteralExpression
    ):
        return expression.left, expression.operator, expression.right.value
    if isinstance(expression.left, LiteralExpression) and isinstance(
        expression.right, ReferenceExpression
    ):
        return (
            expression.right,
            _INVERT_OPERATOR[expression.operator],
            expression.left.value,
        )
    return None


def _reference_semantic_path(reference: ReferenceExpression) -> str | None:
    if reference.record_type is None or not reference.path:
        return None
    return f"{reference.record_type}.{reference.field_path}"


def _single_capability(
    capabilities: tuple[PredicateBindingCapability, ...],
) -> PredicateBindingCapability | None:
    return capabilities[0] if len(capabilities) == 1 else None


def _bind_endpoint(
    units: tuple[_PredicateUnit, ...],
    registry: PredicateBindingRegistry,
    *,
    broker: str,
    origin: str,
    endpoint: str,
) -> EndpointPredicateBinding:
    by_parameter: dict[str, PredicateParameterBinding] = {}
    consumed: list[str] = []
    residual: list[str] = []

    for unit in units:
        parts = _comparison_parts(unit.expression)
        if parts is None:
            residual.append(
                f"{unit.label}: only conjunctive reference-to-literal comparisons "
                "are safe for parameter pushdown"
            )
            continue

        reference, operator, literal = parts
        semantic_path = _reference_semantic_path(reference)
        if semantic_path is None:
            residual.append(f"{unit.label}: semantic reference is unresolved")
            continue
        if reference.channel is not None and reference.channel != broker:
            residual.append(
                f"{unit.label}: semantic channel {reference.channel!r} does not "
                f"match endpoint broker {broker!r}"
            )
            continue

        field_candidates = tuple(
            item
            for item in registry.query(
                broker=broker,
                origin=origin,
                endpoint=endpoint,
                semantic_path=semantic_path,
                value_from="literal",
            )
            if operator in item.operators
        )
        field_binding = _single_capability(field_candidates)
        if field_binding is None:
            residual.append(
                f"{unit.label}: no exact declared binding for "
                f"{semantic_path} {operator}"
            )
            continue
        if field_binding.requires_producer and reference.producer is None:
            residual.append(
                f"{unit.label}: {semantic_path} requires an explicit semantic producer"
            )
            continue

        staged: list[PredicateParameterBinding] = []
        if reference.producer is not None:
            producer_binding = _single_capability(
                registry.query(
                    broker=broker,
                    origin=origin,
                    endpoint=endpoint,
                    semantic_record=reference.record_type,
                    value_from="producer",
                )
            )
            if producer_binding is None and field_binding.requires_producer:
                residual.append(
                    f"{unit.label}: endpoint has no unambiguous producer selector "
                    f"for {reference.record_type}"
                )
                continue
            if producer_binding is not None:
                staged.append(
                    PredicateParameterBinding(
                        physical_name=producer_binding.physical_param,
                        value=reference.producer,
                        value_from="producer",
                        semantic_record=reference.record_type,
                    )
                )

        staged.append(
            PredicateParameterBinding(
                physical_name=field_binding.physical_param,
                value=literal,
                value_from="literal",
                semantic_record=reference.record_type,
                semantic_path=semantic_path,
                operator=operator,
            )
        )

        conflict = next(
            (
                item
                for item in staged
                if item.physical_name in by_parameter
                and by_parameter[item.physical_name].value != item.value
            ),
            None,
        )
        if conflict is not None:
            residual.append(
                f"{unit.label}: conflicting values for physical parameter "
                f"{conflict.physical_name!r}"
            )
            continue

        for item in staged:
            by_parameter.setdefault(item.physical_name, item)
        consumed.append(
            f"{semantic_path} {operator} {literal!r}"
        )

    bindings = tuple(
        by_parameter[name] for name in sorted(by_parameter)
    )
    return EndpointPredicateBinding(
        broker=broker,
        origin=origin,
        endpoint=endpoint,
        bindings=bindings,
        consumed_predicates=tuple(consumed),
        residual_reasons=tuple(residual),
        total_predicates=len(units),
    )


def bind_surface_predicates(
    surface: SurfaceScript,
    graph: CapabilityGraph,
    *,
    predicate_registry: PredicateBindingRegistry | None = None,
    semantic_paths: _SemanticPaths | None = None,
) -> SurfacePredicateBindingReport:
    """Report exact server-filter bindings for first-pass DSL predicates.

    Only conjunctions can be decomposed safely.  ``or``, ``not``, existence
    tests, reference-to-reference comparisons, unsupported operators, missing
    producers, and predicates after the first explicit ``filter`` remain
    residual.  This function does not choose among endpoints.
    """

    model = semantic_paths or _semantic_path_model()
    units = _first_pass_predicates(surface, record_types=model.record_types)
    if not units:
        return SurfacePredicateBindingReport()

    registry = predicate_registry or build_predicate_binding_registry(graph)
    graph_endpoints = {
        (item.broker, item.origin, item.endpoint)
        for item in graph.endpoint_capabilities
    }
    keys = sorted(
        {
            (item.broker, item.origin, item.endpoint)
            for item in registry.capabilities
            if item.origin in surface.candidates.origins
            and (
                surface.candidates.broker is None
                or item.broker == surface.candidates.broker
            )
            and (item.broker, item.origin, item.endpoint) in graph_endpoints
        }
    )

    return SurfacePredicateBindingReport(
        endpoints=tuple(
            _bind_endpoint(
                units,
                registry,
                broker=broker,
                origin=origin,
                endpoint=endpoint,
            )
            for broker, origin, endpoint in keys
        )
    )


__all__ = [
    "EndpointPredicateBinding",
    "PredicateParameterBinding",
    "SurfacePredicateBindingReport",
    "bind_surface_predicates",
]
