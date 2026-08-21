"""Execute conservative local MatchStep operations over normalized Portfolios."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from itertools import combinations
from math import acos, cos, isfinite, radians, sin
import re
from typing import Any

from alertissimo.data_layer.representations import (
    InternalEdgeId,
    InternalPortfolioId,
    Portfolio,
    SemanticEdge,
)
from alertissimo.data_layer.semantic_model import validate_portfolio_against_semantic_model
from alertissimo.orchestration.ir import MatchStep
from alertissimo.orchestration.normalization.models import (
    ExecutionPortfolioResult,
    StepPortfolioResult,
    summary_object_identity,
)


class UnsupportedMatchError(ValueError):
    """Raised when MatchStep asks for semantics not yet implemented safely."""


class MatchInputError(ValueError):
    """Raised when normalized Portfolio evidence is ambiguous or contradictory."""


@dataclass(frozen=True)
class _ObjectGroup:
    """One harmonized matching entity identified by exact survey object identity."""

    identity: tuple[str, str]
    portfolio_ids: tuple[InternalPortfolioId, ...]
    position: tuple[float, float] | None


_POSITION_WITHIN_RE = re.compile(
    r"^\s*position\s+within\s+"
    r"(?P<value>[+]?(?:\d+(?:\.\d*)?|\.\d+))\s*"
    r"(?P<unit>deg|arcmin|arcsec)\s*$",
    re.IGNORECASE,
)
_ANGLE_TO_ARCSEC = {
    "arcsec": 1.0,
    "arcmin": 60.0,
    "deg": 3600.0,
}


def _finite_coordinate(value: Any, *, name: str) -> float:
    if isinstance(value, bool):
        raise MatchInputError(f"summary {name} must be numeric")
    try:
        coordinate = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MatchInputError(f"summary {name} must be numeric") from exc
    if not isfinite(coordinate):
        raise MatchInputError(f"summary {name} must be finite")
    return coordinate


def _summary_positions(portfolio: Portfolio) -> tuple[tuple[float, float], ...]:
    positions: list[tuple[float, float]] = []
    for record in portfolio.records:
        if record.semantic_type.split("@", 1)[0] != "summary":
            continue
        ra_value = record.get("position.ra")
        dec_value = record.get("position.dec")
        if ra_value is None or dec_value is None:
            continue
        ra = _finite_coordinate(ra_value, name="position.ra")
        dec = _finite_coordinate(dec_value, name="position.dec")
        if not 0.0 <= ra < 360.0:
            raise MatchInputError(f"summary position.ra is outside [0, 360): {ra!r}")
        if not -90.0 <= dec <= 90.0:
            raise MatchInputError(f"summary position.dec is outside [-90, 90]: {dec!r}")
        point = (ra, dec)
        if point not in positions:
            positions.append(point)
    return tuple(positions)


def _groups(source: StepPortfolioResult) -> tuple[_ObjectGroup, ...]:
    """Group exact ``(origin, object_id)`` identities before any matching.

    This is deliberately the harmonization boundary for MatchStep input. If the
    same survey object arrived from two or more brokers/executions, those
    execution-local Portfolios form one matching entity. They are never compared
    with each other and therefore can never acquire a cross-Portfolio Match edge.
    The normal ``StepPortfolioResult.portfolios`` view performs the corresponding
    semantic Portfolio consolidation.
    """

    grouped: dict[tuple[str, str], list[Portfolio]] = {}
    order: list[tuple[str, str]] = []
    for execution in source.executions:
        for portfolio in execution.portfolios:
            identity = summary_object_identity(portfolio)
            if identity is None:
                continue
            if identity not in grouped:
                grouped[identity] = []
                order.append(identity)
            if all(
                item.internal_portfolio_id != portfolio.internal_portfolio_id
                for item in grouped[identity]
            ):
                grouped[identity].append(portfolio)

    result: list[_ObjectGroup] = []
    for identity in order:
        portfolios = grouped[identity]
        positions: list[tuple[float, float]] = []
        for portfolio in portfolios:
            for position in _summary_positions(portfolio):
                if position not in positions:
                    positions.append(position)
        if len(positions) > 1:
            raise MatchInputError(
                "matching requires one unambiguous object-level summary position for "
                f"{identity!r}; found {positions!r}"
            )
        result.append(
            _ObjectGroup(
                identity=identity,
                portfolio_ids=tuple(
                    portfolio.internal_portfolio_id for portfolio in portfolios
                ),
                position=positions[0] if positions else None,
            )
        )
    return tuple(result)


def _angular_separation_arcsec(
    left: tuple[float, float], right: tuple[float, float]
) -> float:
    ra1, dec1 = map(radians, left)
    ra2, dec2 = map(radians, right)
    cosine = sin(dec1) * sin(dec2) + cos(dec1) * cos(dec2) * cos(ra1 - ra2)
    cosine = max(-1.0, min(1.0, cosine))
    return acos(cosine) * 206264.80624709636


def _edge_id(
    *, step_index: int, left: tuple[str, str], right: tuple[str, str]
) -> InternalEdgeId:
    endpoints = sorted((f"{left[0]}:{left[1]}", f"{right[0]}:{right[1]}"))
    material = "\0".join(("--spatially_near--", str(step_index), *endpoints))
    digest = sha256(material.encode("utf-8")).hexdigest()[:24]
    return InternalEdgeId(f"edge:match:{step_index}:{digest}")


def _append_edge(portfolio: Portfolio, edge: SemanticEdge) -> Portfolio:
    for existing in portfolio.edges:
        if existing.internal_edge_id != edge.internal_edge_id:
            continue
        if existing != edge:
            raise MatchInputError(
                "conflicting semantic edges share internal edge ID "
                f"{edge.internal_edge_id.value!r}"
            )
        return portfolio
    updated = Portfolio(
        internal_portfolio_id=portfolio.internal_portfolio_id,
        records=portfolio.records,
        edges=portfolio.edges + (edge,),
        executions=portfolio.executions,
    )
    validate_portfolio_against_semantic_model(updated)
    return updated


def _predicate_position_threshold(predicate: Any) -> float | None:
    """Read the existing semantic ``position within <angle>`` Match predicate."""

    if not isinstance(predicate, str):
        return None
    match = _POSITION_WITHIN_RE.fullmatch(predicate)
    if match is None:
        return None
    threshold = float(match.group("value")) * _ANGLE_TO_ARCSEC[
        match.group("unit").lower()
    ]
    return threshold if threshold > 0.0 else None


def _position_match_contract(
    step: MatchStep,
) -> tuple[tuple[str, ...], float]:
    if step.target is not None:
        raise UnsupportedMatchError("target-scoped MatchStep is not implemented yet")
    if step.sources or step.params.get("counterpart_origin") is not None:
        raise UnsupportedMatchError(
            "external-counterpart MatchStep execution is not implemented yet"
        )
    if step.params.get("max_time_delta") is not None:
        raise UnsupportedMatchError(
            "temporal MatchStep execution is deferred until object-level time anchors are defined"
        )

    predicate_threshold = _predicate_position_threshold(step.params.get("predicate"))
    if step.method not in (None, "position"):
        raise UnsupportedMatchError(
            "the first executable MatchStep method is exactly 'position'"
        )
    if step.method is None and predicate_threshold is None:
        raise UnsupportedMatchError(
            "the first executable MatchStep requires 'position within <angle>'"
        )

    raw_origins = step.params.get("candidate_origins")
    if not isinstance(raw_origins, (list, tuple)) or not raw_origins:
        raise UnsupportedMatchError(
            "positional MatchStep requires at least one explicit candidate origin"
        )
    origins = tuple(str(origin) for origin in raw_origins)
    if any(not origin.strip() for origin in origins) or len(set(origins)) != len(origins):
        raise UnsupportedMatchError("candidate_origins must be non-empty and unique")

    threshold_value = step.params.get("max_angular_separation_arcsec")
    if threshold_value is None:
        threshold_value = predicate_threshold
    elif predicate_threshold is not None:
        try:
            explicit = float(threshold_value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise UnsupportedMatchError(
                "max_angular_separation_arcsec must be positive"
            ) from exc
        if not isfinite(explicit) or explicit <= 0.0:
            raise UnsupportedMatchError(
                "max_angular_separation_arcsec must be positive"
            )
        if abs(explicit - predicate_threshold) > 1e-12:
            raise UnsupportedMatchError(
                "positional MatchStep has conflicting explicit and predicate thresholds"
            )
        threshold_value = explicit

    if isinstance(threshold_value, bool):
        raise UnsupportedMatchError("max_angular_separation_arcsec must be positive")
    try:
        threshold = float(threshold_value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise UnsupportedMatchError(
            "positional MatchStep requires max_angular_separation_arcsec or "
            "a 'position within <angle>' predicate"
        ) from exc
    if not isfinite(threshold) or threshold <= 0.0:
        raise UnsupportedMatchError("max_angular_separation_arcsec must be positive")
    return origins, threshold


def match_step_portfolios(
    step: MatchStep,
    source: StepPortfolioResult,
    *,
    step_index: int,
) -> StepPortfolioResult:
    """Return the MatchStep semantic view with positional adjacency edges.

    Matching operates only on normalized object-level summary identity and position.
    It never reads provider payloads and never merges Portfolios. Exact object
    identities are grouped as one matching entity before pair comparison; their
    execution-local Portfolios are harmonized by the Step semantic view rather than
    linked by MatchStep. Once exact identities have been grouped, every distinct
    semantic identity selected by the Match candidate origins is eligible for the
    explicit Match policy, including different object IDs from the same survey.
    For each accepted pair, the same ``InternalEdgeId`` is projected into every
    execution-local constituent of both semantic objects. Step-level consolidation
    then rewrites constituent Portfolio endpoints to their final semantic IDs. The
    returned view belongs to the MatchStep occurrence while retaining the physical
    execution groupings of its candidate/material input.
    """

    origins, threshold = _position_match_contract(step)
    allowed_origins = frozenset(origins)
    groups = tuple(
        group
        for group in _groups(source)
        if group.identity[0] in allowed_origins and group.position is not None
    )

    by_id: dict[InternalPortfolioId, Portfolio] = {}
    for execution in source.executions:
        for portfolio in execution.portfolios:
            existing = by_id.get(portfolio.internal_portfolio_id)
            if existing is not None and existing != portfolio:
                raise MatchInputError(
                    "conflicting Portfolio content shares internal portfolio ID "
                    f"{portfolio.internal_portfolio_id.value!r}"
                )
            by_id[portfolio.internal_portfolio_id] = portfolio

    for left, right in combinations(groups, 2):
        separation = _angular_separation_arcsec(left.position, right.position)
        if separation > threshold:
            continue
        edge_id = _edge_id(step_index=step_index, left=left.identity, right=right.identity)
        fields = {
            "angular_separation": separation,
            "basis": "summary.position",
        }
        left_remote = right.portfolio_ids[0]
        right_remote = left.portfolio_ids[0]

        for local_id in left.portfolio_ids:
            by_id[local_id] = _append_edge(
                by_id[local_id],
                SemanticEdge(
                    edge_id,
                    "--spatially_near--",
                    local_id,
                    left_remote,
                    fields,
                ),
            )
        for local_id in right.portfolio_ids:
            by_id[local_id] = _append_edge(
                by_id[local_id],
                SemanticEdge(
                    edge_id,
                    "--spatially_near--",
                    local_id,
                    right_remote,
                    fields,
                ),
            )

    return StepPortfolioResult(
        step_index=step_index,
        executions=tuple(
            ExecutionPortfolioResult(
                execution_id=execution.execution_id,
                portfolios=tuple(
                    by_id[portfolio.internal_portfolio_id]
                    for portfolio in execution.portfolios
                ),
            )
            for execution in source.executions
        ),
    )


__all__ = [
    "MatchInputError",
    "UnsupportedMatchError",
    "match_step_portfolios",
]
