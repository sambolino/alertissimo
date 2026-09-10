"""Deterministic DSL rendering for the constrained visual block builder.

The builder keeps its fields structured and renders the same canonical text that
the parser receives.  In particular, only predicates scoped under a ``with``
block are indented; ordinary clauses always start in column zero.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re


_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
_ANGLE_UNITS = frozenset({"deg", "arcmin", "arcsec"})


@dataclass(frozen=True)
class BlockRequirement:
    """One capability-selected ``with PRODUCT via BROKER`` block."""

    product: str
    broker: str


def _identifier(value: str, *, field: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field} must be a DSL identifier")
    return value


def _finite(value: float, *, field: str, minimum: float, maximum: float) -> float:
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return value


def render_block_dsl(
    *,
    origins: tuple[str, ...],
    broker: str,
    ra_deg: float,
    dec_deg: float,
    radius: float,
    radius_unit: str,
    latest: int | None = None,
    requirements: tuple[BlockRequirement, ...] = (),
) -> str:
    """Render the supported search blocks as canonical, parser-ready DSL text."""

    if not origins:
        raise ValueError("at least one candidate origin is required")
    normalized_origins = tuple(_identifier(origin, field="origin") for origin in origins)
    if len(set(normalized_origins)) != len(normalized_origins):
        raise ValueError("candidate origins must be unique")
    broker = _identifier(broker, field="broker")
    ra_deg = _finite(ra_deg, field="RA", minimum=0, maximum=math.nextafter(360, 0))
    dec_deg = _finite(dec_deg, field="Dec", minimum=-90, maximum=90)
    radius = _finite(radius, field="radius", minimum=math.nextafter(0, 1), maximum=1e9)
    if radius_unit not in _ANGLE_UNITS:
        raise ValueError("radius unit must be deg, arcmin, or arcsec")
    if latest is not None and latest <= 0:
        raise ValueError("latest must be a positive integer")

    lines = [
        f"objects from {', '.join(normalized_origins)} via {broker}",
        f"inside ({ra_deg:.5f}, {dec_deg:.5f}, {radius:g}{radius_unit})",
    ]
    if latest is not None:
        lines.append(f"latest {latest}")
    for requirement in requirements:
        product = _identifier(requirement.product, field="product")
        requirement_broker = _identifier(requirement.broker, field="requirement broker")
        lines.append(f"with {product} via {requirement_broker}")
    return "\n".join(lines) + "\n"


__all__ = ["BlockRequirement", "render_block_dsl"]
