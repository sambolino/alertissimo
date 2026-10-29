"""Pure UTC window validation and physical time encodings; no clock or IR imports."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone


def utc_instant(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("time values must be timezone-aware datetimes")
    return value.astimezone(timezone.utc)


def validate_time_context(context: Mapping) -> None:
    """Check representability without reading a clock or resolving relative intent."""
    if not isinstance(context, Mapping):
        raise ValueError("time context must be a mapping")
    mode = context.get("mode", "detection")
    if not isinstance(mode, str) or mode not in {"detection", "first", "last"}:
        raise ValueError("time selection mode must be detection, first, or last")
    if context.get("offset") is not None or context.get("sampling") is not None:
        raise ValueError("time offset and sampling have no declared window translation")
    window = context.get("window")
    start, end = context.get("start_time"), context.get("end_time")
    if window is not None:
        if not isinstance(window, timedelta) or window <= timedelta(0):
            raise ValueError("relative time window must be positive")
        if start is not None or end is not None or context.get("relative_to") != "now":
            raise ValueError("relative time requires only a window relative to now")
    else:
        if context.get("relative_to") is not None:
            raise ValueError("absolute time bounds cannot also be relative")
        if utc_instant(start) > utc_instant(end):
            raise ValueError("time start must not exceed time end")


def resolve_time_context(context: Mapping, reference_time: datetime | None) -> dict[str, datetime | str]:
    validate_time_context(context)
    if context.get("window") is not None:
        end = utc_instant(reference_time)
        bounds = {"start": end - context["window"], "end": end}
    else:
        bounds = {"start": utc_instant(context["start_time"]), "end": utc_instant(context["end_time"])}
    return {**bounds, "mode": context.get("mode", "detection")}


def validate_time_encoding(bound: str, encoding: str) -> None:
    if not isinstance(bound, str) or bound not in {"start", "end", "range"}:
        raise ValueError("time bound must be start, end, or range")
    if not isinstance(encoding, str) or encoding not in {"utc_iso", "mjd", "jd"}:
        raise ValueError("time encoding must be utc_iso, mjd, or jd")


def time_bound(*, time_context: Mapping, bound: str, encoding: str):
    """Encode resolved UTC bounds exactly as declared; never shift boundaries.

    MJD/JD are UTC day numbers, subject to floating-point precision. No conversion
    to TAI/TT or leap-second representation is implied by this datetime encoder.
    """
    validate_time_encoding(bound, encoding)
    if time_context.get("mode", "detection") != "detection":
        raise ValueError("first/last within requires a declared candidate-time translation; the existing time_bound adapter only encodes detection windows")

    def encode(value):
        value = utc_instant(value)
        if encoding == "utc_iso":
            return value.isoformat(timespec="microseconds").replace("+00:00", "Z")
        mjd = (value - datetime(1858, 11, 17, tzinfo=timezone.utc)).total_seconds() / 86400
        return mjd if encoding == "mjd" else mjd + 2400000.5

    if bound == "range":
        return [encode(time_context["start"]), encode(time_context["end"])]
    return encode(time_context[bound])
