"""Small structured query encoders used by declared predicate bindings."""

from __future__ import annotations

import math
import re
from typing import Any


_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_RANGE_OPERATOR = {"<": "lt", "<=": "lte", ">": "gt", ">=": "gte"}


def numeric_comparison(field: str, operator: str, value: Any) -> dict:
    """Encode one finite numeric comparison, without raw query-string syntax."""
    if not isinstance(field, str) or not _FIELD.fullmatch(field):
        raise ValueError("invalid Elasticsearch field identifier")
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Elasticsearch comparison requires a finite numeric literal")
    if operator == "=":
        clause = {"term": {field: value}}
    elif operator in _RANGE_OPERATOR:
        clause = {"range": {field: {_RANGE_OPERATOR[operator]: value}}}
    else:
        raise ValueError("unsupported Elasticsearch numeric operator")
    return {"query": clause}


def conjoin(left: dict, right: dict) -> dict:
    """Join two compiler-produced requests under the client's sole query key."""
    for query in (left, right):
        if not isinstance(query, dict) or set(query) != {"query"} or not isinstance(query["query"], dict):
            raise ValueError("Elasticsearch conditions require one top-level query key")
    return {"query": {"bool": {"filter": [left["query"], right["query"]]}}}
