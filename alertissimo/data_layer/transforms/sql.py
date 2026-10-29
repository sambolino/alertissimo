"""Pure, provider-neutral transforms for constrained SQL request fragments."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

from .temporal import time_bound


_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def string_membership_condition(
    target_id: Any,
    *,
    column: str,
    value_pattern: str,
) -> str:
    """Build a quoted SQL ``IN`` condition from validated canonical IDs."""

    if not _COLUMN.fullmatch(column):
        raise ValueError(f"invalid SQL membership column {column!r}")
    values = target_id if isinstance(target_id, (list, tuple)) else (target_id,)
    if not values:
        raise ValueError("SQL membership condition requires at least one value")

    pattern = re.compile(value_pattern)
    normalized = tuple(str(value) for value in values)
    invalid = tuple(value for value in normalized if not pattern.fullmatch(value))
    if invalid:
        raise ValueError(f"invalid SQL membership values: {invalid!r}")

    quoted = ",".join(f'"{value}"' for value in normalized)
    return f"{column} IN ({quoted})"


def numeric_comparison(column: str, operator: str, value: Any, *, subtract: float = 0) -> str:
    """Render a declared numeric comparison; never interpolate arbitrary text.

    Subtraction operates on the raw column, matching the response transform
    without rounding a canonical bound through an inverse unit conversion.
    """
    if not _COLUMN.fullmatch(column) or operator not in {"=", "<", "<=", ">", ">="}:
        raise ValueError("invalid SQL comparison column or operator")
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("SQL comparison requires a finite numeric literal")
    if type(subtract) not in (int, float) or not math.isfinite(subtract):
        raise ValueError("SQL subtraction requires a finite number")
    expression = f"({column} - {subtract!r})" if subtract else column
    return f"{expression} {operator} {value!r}"


def validate_time_window_options(*, first_column: str, last_column: str,
                                 subtract: float, order_by: str) -> None:
    for column in (first_column, last_column, order_by):
        if not isinstance(column, str) or not _COLUMN.fullmatch(column):
            raise ValueError("invalid SQL time column or ordering identifier")
    if first_column == last_column:
        raise ValueError("first and last SQL time columns must be distinct")
    if type(subtract) not in (int, float) or not math.isfinite(subtract):
        raise ValueError("SQL time subtraction requires a finite number")


def time_window_condition(*, time_context: Mapping, first_column: str,
                          last_column: str, subtract: float, order_by: str) -> str:
    """Encode a resolved window using declared summary columns and subtraction.

    Detection mode is a safe summary-overlap prefilter, never an existence proof.
    A recipe must supply required detection evidence for actual membership.
    First/last modes encode the corresponding closed summary-time interval.
    """
    validate_time_window_options(first_column=first_column, last_column=last_column,
                                 subtract=subtract, order_by=order_by)
    mode = time_context.get("mode", "detection")
    start, end = time_bound(time_context=time_context, bound="range", encoding="mjd", mode=mode)
    lower_column = last_column if mode in ("detection", "last") else first_column
    upper_column = first_column if mode in ("detection", "first") else last_column
    lower = numeric_comparison(lower_column, ">=", start, subtract=subtract)
    upper = numeric_comparison(upper_column, "<=", end, subtract=subtract)
    return f"({lower}) AND ({upper}) ORDER BY {order_by}"


def conjoin_ordered_conditions(left: str, right: str) -> str:
    """Conjoin two compiled WHERE fragments, keeping one matching ORDER BY.

    These inputs are trusted compiler/encoder products, not public raw SQL.
    Reject mismatched/missing ordering rather than guessing how to combine it.
    """
    parts = []
    ordering = None
    for value in (left, right):
        if not isinstance(value, str) or value.count(" ORDER BY ") != 1:
            raise ValueError("SQL composition requires one declared ordering per fragment")
        body, _, column = value.partition(" ORDER BY ")
        if not body.strip() or not _COLUMN.fullmatch(column):
            raise ValueError("invalid compiled SQL condition or ordering")
        if ordering is not None and column != ordering:
            raise ValueError("SQL condition orderings conflict")
        ordering = column
        parts.append(body)
    return f"({parts[0]}) AND ({parts[1]}) ORDER BY {ordering}"


__all__ = ["string_membership_condition", "numeric_comparison", "time_window_condition",
           "validate_time_window_options", "conjoin_ordered_conditions"]
