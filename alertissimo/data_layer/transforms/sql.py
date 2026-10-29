"""Pure, provider-neutral transforms for constrained SQL request fragments."""

from __future__ import annotations

import math
import re
from typing import Any


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


__all__ = ["string_membership_condition", "numeric_comparison"]
