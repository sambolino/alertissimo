"""Evaluate semantic predicates against normalized Portfolio data.

This is the second filtering realization: predicates not safely expressible as
provider input constraints are evaluated after normalization and prune candidate
Portfolios without changing the semantic condition itself.
"""

from __future__ import annotations

import math
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


def _record_matches(record: SemanticRecord, reference: SemanticReference, portfolio: Portfolio) -> bool:
    noun, producer, channel = _record_parts(record.semantic_type)
    if noun != reference.semantic_type:
        return False
    if reference.producer is not None and producer != reference.producer:
        return False
    if channel is None and reference.channel is not None and record.internal_source is not None:
        # Legacy fixed-producer records (for example classification@fink) omit
        # the channel suffix. Only their own execution provenance can supply it;
        # another broker present in the Portfolio is not evidence for this record.
        execution = portfolio.execution(record.internal_source.internal_execution_id)
        channel = execution.broker if execution is not None else None
    if reference.channel is not None and channel != reference.channel:
        return False
    return True


def _record_value(record: SemanticRecord, reference: SemanticReference, portfolio: Portfolio) -> Any:
    if not _record_matches(record, reference, portfolio):
        return _MISSING
    if not reference.field_path:
        return True
    return record.get(reference.field_path, _MISSING)


def _available(value: Any) -> bool:
    return value is not _MISSING and value is not None and not (
        isinstance(value, float) and not math.isfinite(value)
    )


def _compare(left: Any, operator_name: str, right: Any) -> bool | None:
    """None is unavailable evidence, and must remain unavailable under NOT."""
    if not _available(left) or not _available(right):
        return None
    numeric = (int, float)
    if isinstance(left, bool) or isinstance(right, bool):
        compatible = isinstance(left, bool) and isinstance(right, bool)
    else:
        compatible = (
            isinstance(left, numeric) and isinstance(right, numeric)
            or isinstance(left, str) and isinstance(right, str)
        )
    if not compatible:
        return None
    try:
        return bool(_COMPARATORS[operator_name](left, right))
    except (TypeError, ValueError):
        return None


def _matching_records(
    portfolio: Portfolio,
    selector: tuple[str, str | None, str | None],
) -> tuple[SemanticRecord, ...]:
    probe = SemanticReference(
        semantic_type=selector[0],
        producer=selector[1],
        channel=selector[2],
    )
    return tuple(record for record in portfolio.records if _record_matches(record, probe, portfolio))


def evaluate_portfolio_predicate(portfolio: Portfolio, predicate: Predicate) -> bool:
    """Return whether a normalized candidate Portfolio satisfies ``predicate``.

    Bind one record per exact (noun, producer, channel) selector for the whole
    expression, independent of Boolean grouping. Repeated fields therefore
    belong to the same assertion even in a mixed classification/summary AND.
    Different explicitly qualified selectors retain independent witnesses.

    Comparisons use three-valued logic: missing, null, nonfinite and incompatible
    values are unknown; NOT cannot turn them into evidence. Only True selects.
    Explicit NOT EXISTS asks about absence in this materialized Portfolio, not
    absence from an unqueried provider. A partial record cannot establish field
    absence if another matching record supplies that field.
    """
    selectors = tuple(dict.fromkeys(_selector(ref) for ref in iter_semantic_references(predicate)))
    records = {key: _matching_records(portfolio, key) for key in selectors}
    bound: dict[tuple[str, str | None, str | None], SemanticRecord | None] = {}

    def operand_value(operand):
        if isinstance(operand, PredicateLiteral):
            return operand.value
        record = bound.get(_selector(operand))
        return _MISSING if record is None else _record_value(record, operand, portfolio)

    def evaluate(node: Predicate, *, negate: bool = False) -> bool | None:
        if isinstance(node, NotPredicate):
            return evaluate(node.operand, negate=not negate)
        if isinstance(node, ExistsPredicate) and negate:
            # Absence is a property of the complete current view of this
            # selector, not of whichever partial row is being tried as witness.
            return not any(
                _available(_record_value(record, node.reference, portfolio))
                for record in records[_selector(node.reference)]
            )
        if isinstance(node, ComparisonPredicate):
            value = _compare(operand_value(node.left), node.operator, operand_value(node.right))
        elif isinstance(node, ExistsPredicate):
            if _selector(node.reference) not in bound:
                return None
            value = _available(operand_value(node.reference))
        elif isinstance(node, BooleanPredicate):
            # Applying negation recursively preserves unknown values and also
            # makes NOT (EXISTS ...) consistent through De Morgan's laws.
            conjunction = (node.operator == "and") != negate
            unknown = False
            for child in node.operands:
                value = evaluate(child, negate=negate)
                if value is None:
                    unknown = True
                elif value != conjunction:
                    return value
            return None if unknown else conjunction
        else:
            return None
        return None if value is None else (not value if negate else value)

    def search(index: int) -> bool:
        value = evaluate(predicate)
        if value is not None:
            return value
        if index == len(selectors):
            return False
        key = selectors[index]
        # An absent selector must leave OR branches evaluable. Its comparisons
        # remain unknown; positive existence is false, explicit absence is true.
        for record in records[key] or (None,):
            bound[key] = record
            if search(index + 1):
                return True
        del bound[key]
        return False

    # Search lazily and stop on a proved result; no Cartesian product is stored.
    return search(0)


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
