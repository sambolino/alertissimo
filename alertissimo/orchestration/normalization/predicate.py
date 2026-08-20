"""Evaluate semantic predicates against normalized Portfolio data.

This is the second filtering realization: predicates not safely expressible as
provider input constraints are evaluated after normalization and prune candidate
Portfolios without changing the semantic condition itself.
"""

from __future__ import annotations

import operator
from typing import Any

from alertissimo.data_layer.representations import Portfolio, SemanticRecord
from alertissimo.orchestration.ir.predicates import (
    BooleanPredicate,
    ComparisonPredicate,
    ExistsPredicate,
    NotPredicate,
    Predicate,
    PredicateLiteral,
    SemanticReference,
    iter_semantic_references,
)


_COMPARATORS = {
    "=": operator.eq,
    "!=": operator.ne,
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}
_MISSING = object()


def _record_parts(semantic_type: str) -> tuple[str, str | None, str | None]:
    noun, at, qualifiers = semantic_type.partition("@")
    if not at:
        return noun, None, None
    producer, colon, channel = qualifiers.partition(":")
    return noun, producer or None, (channel or None) if colon else None


def _selector(reference: SemanticReference) -> tuple[str, str | None, str | None]:
    return reference.semantic_type, reference.producer, reference.channel


def _record_matches(record: SemanticRecord, reference: SemanticReference) -> bool:
    noun, producer, channel = _record_parts(record.semantic_type)
    if noun != reference.semantic_type:
        return False
    if reference.producer is not None and producer != reference.producer:
        return False
    if reference.channel is not None and channel != reference.channel:
        return False
    return True


def _record_value(record: SemanticRecord, reference: SemanticReference) -> Any:
    if not _record_matches(record, reference):
        return _MISSING
    if not reference.field_path:
        return True
    return record.get(reference.field_path, _MISSING)


def _compare(left: Any, operator_name: str, right: Any) -> bool:
    if left is _MISSING or right is _MISSING:
        return False
    try:
        return bool(_COMPARATORS[operator_name](left, right))
    except (TypeError, ValueError):
        return False


def _operand_on_record(operand, record: SemanticRecord) -> Any:
    if isinstance(operand, PredicateLiteral):
        return operand.value
    return _record_value(record, operand)


def _evaluate_on_record(predicate: Predicate, record: SemanticRecord) -> bool:
    if isinstance(predicate, ComparisonPredicate):
        return _compare(
            _operand_on_record(predicate.left, record),
            predicate.operator,
            _operand_on_record(predicate.right, record),
        )
    if isinstance(predicate, ExistsPredicate):
        return _record_value(record, predicate.reference) is not _MISSING
    if isinstance(predicate, NotPredicate):
        return not _evaluate_on_record(predicate.operand, record)
    if isinstance(predicate, BooleanPredicate):
        values = (_evaluate_on_record(item, record) for item in predicate.operands)
        return all(values) if predicate.operator == "and" else any(values)
    return False


def _single_selector(predicate: Predicate):
    selectors = {_selector(ref) for ref in iter_semantic_references(predicate)}
    return next(iter(selectors)) if len(selectors) == 1 else None


def _matching_records(
    portfolio: Portfolio,
    selector: tuple[str, str | None, str | None],
) -> tuple[SemanticRecord, ...]:
    probe = SemanticReference(
        semantic_type=selector[0],
        producer=selector[1],
        channel=selector[2],
    )
    return tuple(record for record in portfolio.records if _record_matches(record, probe))


def _values(portfolio: Portfolio, operand) -> tuple[Any, ...]:
    if isinstance(operand, PredicateLiteral):
        return (operand.value,)
    return tuple(
        value
        for record in portfolio.records
        for value in [_record_value(record, operand)]
        if value is not _MISSING
    )


def evaluate_portfolio_predicate(portfolio: Portfolio, predicate: Predicate) -> bool:
    """Return whether a normalized candidate Portfolio satisfies ``predicate``.

    When a predicate subtree references one semantic record selector, it is
    evaluated against individual matching records so conjunctive fields remain
    correlated to the same semantic assertion instead of being satisfied by
    unrelated records.
    """

    selector = _single_selector(predicate)
    if selector is not None:
        return any(
            _evaluate_on_record(predicate, record)
            for record in _matching_records(portfolio, selector)
        )

    if isinstance(predicate, ComparisonPredicate):
        return any(
            _compare(left, predicate.operator, right)
            for left in _values(portfolio, predicate.left)
            for right in _values(portfolio, predicate.right)
        )
    if isinstance(predicate, ExistsPredicate):
        return bool(_values(portfolio, predicate.reference))
    if isinstance(predicate, NotPredicate):
        return not evaluate_portfolio_predicate(portfolio, predicate.operand)
    if isinstance(predicate, BooleanPredicate):
        values = (
            evaluate_portfolio_predicate(portfolio, item)
            for item in predicate.operands
        )
        return all(values) if predicate.operator == "and" else any(values)
    return False


def prune_portfolios(
    portfolios: tuple[Portfolio, ...] | list[Portfolio],
    predicate: Predicate,
) -> tuple[Portfolio, ...]:
    """Keep only normalized candidate Portfolios satisfying a residual predicate."""

    return tuple(
        portfolio
        for portfolio in portfolios
        if evaluate_portfolio_predicate(portfolio, predicate)
    )


__all__ = ["evaluate_portfolio_predicate", "prune_portfolios"]
