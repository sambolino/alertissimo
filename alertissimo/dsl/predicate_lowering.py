"""Translate resolved DSL expressions into provider-independent IR predicates."""

from __future__ import annotations

from alertissimo.orchestration.ir import (
    BooleanPredicate,
    ComparisonPredicate,
    ExistsPredicate,
    NotPredicate,
    Predicate,
    PredicateLiteral,
    SemanticReference,
)

from alertissimo.data_layer.runtime.classification_headline import resolve_taxon

from .expression import (
    BooleanExpression,
    ComparisonExpression,
    ExistsExpression,
    Expression,
    LiteralExpression,
    NotExpression,
    ReferenceExpression,
)
from .validation import resolve_expression_references


class PredicateLoweringError(ValueError):
    """A syntactically valid expression is not ontology-grounded enough for IR."""


def _reference(reference: ReferenceExpression) -> SemanticReference:
    if reference.record_type is None:
        raise PredicateLoweringError(
            f"expression reference {reference.root!r} is not grounded in an ontology record"
        )
    return SemanticReference(
        semantic_type=reference.record_type,
        field_path=reference.field_path,
        producer=reference.producer,
        channel=reference.channel,
    )


def _operand(value: ReferenceExpression | LiteralExpression):
    if isinstance(value, ReferenceExpression):
        return _reference(value)
    return PredicateLiteral(value=value.value)


def lower_expression_predicate(
    expression: Expression | str,
    record_types: frozenset[str],
    *,
    scoped_noun: str | None = None,
    scoped_producer: str | None = None,
    scoped_channel: str | None = None,
) -> Predicate:
    """Resolve semantic scope and lower one DSL expression into canonical IR."""

    resolved = resolve_expression_references(
        expression,
        record_types,
        scoped_noun=scoped_noun,
        scoped_producer=scoped_producer,
        scoped_channel=scoped_channel,
    )

    def lower(node) -> Predicate:
        if isinstance(node, ComparisonExpression):
            left, right = _operand(node.left), _operand(node.right)
            for reference, literal in ((left, right), (right, left)):
                if (isinstance(reference, SemanticReference)
                        and reference.semantic_type == "classification"
                        and reference.field_path == "best.taxon"):
                    if node.operator not in {"=", "!="} or not isinstance(literal, PredicateLiteral):
                        raise PredicateLoweringError(
                            "classification.best.taxon requires = or != with an alias or code; "
                            f"got {node.operator} {getattr(literal, 'value', literal)!r}"
                        )
                    try:
                        resolved_literal = PredicateLiteral(value=resolve_taxon(literal.value))
                    except ValueError as exc:
                        raise PredicateLoweringError(str(exc)) from exc
                    if reference is left:
                        right = resolved_literal
                    else:
                        left = resolved_literal
                    break
            return ComparisonPredicate(operator=node.operator, left=left, right=right)
        if isinstance(node, BooleanExpression):
            return BooleanPredicate(
                operator=node.operator,
                operands=tuple(lower(item) for item in node.operands),
            )
        if isinstance(node, NotExpression):
            return NotPredicate(operand=lower(node.operand))
        if isinstance(node, ExistsExpression):
            return ExistsPredicate(reference=_reference(node.operand))
        raise PredicateLoweringError(
            f"unsupported expression node {type(node).__name__}"
        )

    return lower(resolved)


__all__ = ["PredicateLoweringError", "lower_expression_predicate"]
