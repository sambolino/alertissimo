"""Project normalized Portfolio detections into plotting rows.

This module deliberately understands semantic paths, not provider payload keys.
It is a presentation adapter only: the returned frame is not a domain model.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import math
import re
from typing import Any

import pandas as pd

from alertissimo.data_layer.representations import Portfolio, SemanticRecord


LIGHTCURVE_COLUMNS = [
    "record_id",
    "semantic_type",
    "mjd",
    "band",
    "measurement_kind",
    "quantity",
    "value",
    "error",
]

# Ordered explicitly so adding another normalized observation-time field is a
# conscious, testable choice. Processing and summary times are not fallbacks.
DEFAULT_TIME_FIELD_PATHS = ("time.mjd",)

_MEASUREMENT_PATH = re.compile(
    r"^(?P<kind>photometry|forced_photometry)\."
    r"(?P<band>[^.]+)\."
    r"(?:(?:psf)\.)?"
    r"(?P<quantity>mag|flux)$"
)


def select_mjd(
    fields: Mapping[str, Any],
    time_field_paths: Sequence[str] = DEFAULT_TIME_FIELD_PATHS,
) -> float | None:
    """Select the first finite numeric normalized time value in priority order."""
    for path in time_field_paths:
        value = fields.get(path)
        if isinstance(value, bool):
            continue
        try:
            mjd = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(mjd):
            return mjd
    return None


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _is_detection(semantic_type: str) -> bool:
    """Ignore producer and broker qualification when identifying detections."""
    return semantic_type.split("@", 1)[0] == "detection"


def _rows_for_record(
    record_id: str,
    semantic_type: str,
    fields: Mapping[str, Any],
    time_field_paths: Sequence[str],
) -> Iterable[dict[str, Any]]:
    if not _is_detection(semantic_type):
        return
    mjd = select_mjd(fields, time_field_paths)
    if mjd is None:
        return

    for path, raw_value in fields.items():
        match = _MEASUREMENT_PATH.fullmatch(path)
        if match is None:
            continue
        value = _finite_number(raw_value)
        if value is None:
            continue
        error = _finite_number(fields.get(f"{path}.error"))
        yield {
            "record_id": record_id,
            "semantic_type": semantic_type,
            "mjd": mjd,
            "band": match.group("band"),
            "measurement_kind": (
                "forced" if match.group("kind") == "forced_photometry" else "ordinary"
            ),
            "quantity": match.group("quantity"),
            "value": value,
            "error": error,
        }


def portfolio_lightcurve_dataframe(
    portfolio: Portfolio,
    *,
    time_field_paths: Sequence[str] = DEFAULT_TIME_FIELD_PATHS,
) -> pd.DataFrame:
    """Project an in-memory :class:`Portfolio` into a neutral plotting frame."""
    if not isinstance(portfolio, Portfolio):
        raise TypeError("portfolio must be an in-memory Portfolio")
    rows = (
        row
        for record in portfolio.records
        for row in _rows_for_record(
            record.internal_record_id.value,
            record.semantic_type,
            record.fields,
            time_field_paths,
        )
    )
    return _frame(rows)


def serialized_portfolio_lightcurve_dataframe(
    data: Mapping[str, Any],
    *,
    time_field_paths: Sequence[str] = DEFAULT_TIME_FIELD_PATHS,
) -> pd.DataFrame:
    """Project the stable ``portfolio_to_dict`` representation for standalone UIs."""
    records = data.get("records")
    if not isinstance(records, list):
        raise ValueError("serialized Portfolio must contain a records array")
    rows: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, Mapping):
            raise ValueError("each serialized Portfolio record must be an object")
        record_id = item.get("internal_record_id")
        semantic_type = item.get("semantic_type")
        fields = item.get("fields")
        if not isinstance(record_id, str) or not isinstance(semantic_type, str) or not isinstance(fields, Mapping):
            raise ValueError("serialized Portfolio records require internal_record_id, semantic_type, and fields")
        rows.extend(_rows_for_record(record_id, semantic_type, fields, time_field_paths))
    return _frame(rows)


def _frame(rows: Iterable[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=LIGHTCURVE_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values(["mjd", "record_id", "measurement_kind", "quantity"], kind="stable")
        frame = frame.reset_index(drop=True)
    return frame


def record_object_id(record: SemanticRecord) -> str | None:
    """Return a normalized object identifier useful for grouping detections."""
    value = record.fields.get("identity.object_id")
    return str(value) if value is not None else None
