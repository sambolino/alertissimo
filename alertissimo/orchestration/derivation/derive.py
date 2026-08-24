"""Apply local DeriveStep operations after provider normalization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Any

from alertissimo.data_layer.representations import (
    InternalRecordId,
    Portfolio,
    SemanticRecord,
)
from alertissimo.data_layer.semantic_model import validate_portfolio_against_semantic_model
from alertissimo.orchestration.ir import (
    ColorColorStep,
    ColorMagnitudeStep,
    DeriveStep,
    LightcurveStep,
)
from alertissimo.orchestration.normalization.models import (
    StepPortfolioResult,
    WorkflowPortfolioResult,
)
from alertissimo.orchestration.runtime import StepRunState


class UnsupportedDerivationError(ValueError):
    """Raised when a declared derivation cannot yet be applied safely."""


@dataclass(frozen=True)
class _TimedValue:
    time_mjd: float
    value: Any
    error: Any | None
    ordinal: int


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return converted if isfinite(converted) else None


def _timed_values(
    portfolio: Portfolio,
    value_path: str,
    error_path: str | None = None,
) -> tuple[_TimedValue, ...]:
    """Find time-tagged values inside intrinsic arrays of lightcurve records."""

    found: list[_TimedValue] = []
    ordinal = 0
    for record in portfolio.records:
        if record.semantic_type.split("@", 1)[0] != "lightcurve":
            continue
        for container in record.fields.values():
            if not _is_sequence(container):
                continue
            for item in container:
                if not isinstance(item, Mapping) or value_path not in item:
                    continue
                time_mjd = _finite_float(item.get("time.mjd"))
                value = item.get(value_path)
                if time_mjd is None or _finite_float(value) is None:
                    continue
                error = item.get(error_path) if error_path else None
                if error is not None and _finite_float(error) is None:
                    error = None
                found.append(_TimedValue(time_mjd, value, error, ordinal))
                ordinal += 1
    return tuple(found)


def _match_nearest(
    left: tuple[_TimedValue, ...],
    right: tuple[_TimedValue, ...],
    tolerance_days: float,
) -> tuple[tuple[_TimedValue, _TimedValue], ...]:
    """Greedily form deterministic one-to-one nearest-time pairs."""

    used_right: set[int] = set()
    pairs: list[tuple[_TimedValue, _TimedValue]] = []
    for left_item in left:
        candidates = [
            (
                abs(left_item.time_mjd - right_item.time_mjd),
                right_item.time_mjd,
                right_item.ordinal,
                index,
                right_item,
            )
            for index, right_item in enumerate(right)
            if index not in used_right
            and abs(left_item.time_mjd - right_item.time_mjd) <= tolerance_days
        ]
        if not candidates:
            continue
        _, _, _, index, right_item = min(candidates)
        used_right.add(index)
        pairs.append((left_item, right_item))
    return tuple(pairs)


def _replace_derived_record(
    portfolio: Portfolio,
    *,
    step_index: int,
    semantic_type: str,
    points: tuple[Mapping[str, Any], ...],
) -> Portfolio:
    if not points:
        return portfolio

    base = semantic_type.split("@", 1)[0]
    record_id = InternalRecordId(f"record:derive:{step_index}:{base}")
    derived = SemanticRecord(
        internal_record_id=record_id,
        semantic_type=semantic_type,
        fields={"points": points},
        internal_source=None,
    )
    records = tuple(
        record for record in portfolio.records if record.internal_record_id != record_id
    ) + (derived,)
    complemented = Portfolio(
        internal_portfolio_id=portfolio.internal_portfolio_id,
        records=records,
        edges=portfolio.edges,
        executions=portfolio.executions,
    )
    validate_portfolio_against_semantic_model(complemented)
    return complemented


def _derive_color_magnitude(
    step: ColorMagnitudeStep, portfolio: Portfolio, step_index: int
) -> Portfolio:
    color_path = f"color.{step.color}.diff"
    colors = _timed_values(portfolio, color_path, f"color.{step.color}.error")
    magnitudes = _timed_values(
        portfolio, step.magnitude_field, f"{step.magnitude_field}.error"
    )
    tolerance = step.max_time_delta.total_seconds() / 86400.0
    points = []
    for color, magnitude in _match_nearest(colors, magnitudes, tolerance):
        point: dict[str, Any] = {
            color_path: color.value,
            step.magnitude_field: magnitude.value,
        }
        if color.error is not None:
            point[f"color.{step.color}.error"] = color.error
        if magnitude.error is not None:
            point[f"{step.magnitude_field}.error"] = magnitude.error
        points.append(point)
    return _replace_derived_record(
        portfolio,
        step_index=step_index,
        semantic_type="color_magnitude@alertissimo",
        points=tuple(points),
    )


def _derive_color_color(
    step: ColorColorStep, portfolio: Portfolio, step_index: int
) -> Portfolio:
    x_path = f"color.{step.color_x}.diff"
    y_path = f"color.{step.color_y}.diff"
    xs = _timed_values(portfolio, x_path, f"color.{step.color_x}.error")
    ys = _timed_values(portfolio, y_path, f"color.{step.color_y}.error")
    tolerance = step.max_time_delta.total_seconds() / 86400.0
    points = []
    for x_value, y_value in _match_nearest(xs, ys, tolerance):
        point: dict[str, Any] = {x_path: x_value.value, y_path: y_value.value}
        if x_value.error is not None:
            point[f"color.{step.color_x}.error"] = x_value.error
        if y_value.error is not None:
            point[f"color.{step.color_y}.error"] = y_value.error
        points.append(point)
    return _replace_derived_record(
        portfolio,
        step_index=step_index,
        semantic_type="color_color@alertissimo",
        points=tuple(points),
    )


def derive_portfolio(
    step: DeriveStep, portfolio: Portfolio, *, step_index: int
) -> Portfolio:
    """Apply one local derivation to one already-normalized Portfolio."""

    if step.target is not None:
        raise UnsupportedDerivationError(
            "target-scoped derivation is deferred until Portfolio-to-target "
            "association is modeled explicitly"
        )
    if isinstance(step, ColorMagnitudeStep):
        return _derive_color_magnitude(step, portfolio, step_index)
    if isinstance(step, ColorColorStep):
        return _derive_color_color(step, portfolio, step_index)
    if isinstance(step, LightcurveStep):
        raise UnsupportedDerivationError(
            "Alertissimo LightcurveStep construction semantics are not implemented yet"
        )
    raise UnsupportedDerivationError(
        f"no derivation executor registered for {type(step).__name__}"
    )


def derive_step_portfolios(
    step: DeriveStep,
    source: StepPortfolioResult,
    *,
    step_index: int,
) -> StepPortfolioResult:
    """Create Derive's own material view without claiming physical executions.

    The input Step remains immutable. The output Portfolios retain the inherited
    records, edges, and real execution provenance contained in the semantic
    material, while the Derive occurrence itself owns zero physical executions.
    """

    return StepPortfolioResult(
        step_index=step_index,
        executions=(),
        materialized_portfolios=tuple(
            derive_portfolio(step, portfolio, step_index=step_index)
            for portfolio in source.portfolios
        ),
    )


def _mark_derive_succeeded(run, step_index: int):
    step_run = run.steps[step_index].model_copy(
        update={"state": StepRunState.SUCCEEDED, "execution_ids": (), "error": None}
    )
    steps = list(run.steps)
    steps[step_index] = step_run
    return run.model_copy(update={"steps": tuple(steps)})


def derive_workflow_portfolios(result: WorkflowPortfolioResult) -> WorkflowPortfolioResult:
    """Run DeriveSteps as occurrence-owned post-normalization material transforms.

    Physical execution provenance is never fabricated for a local derivation. Each
    DeriveStep consumes exactly the earlier semantic view declared by its
    ``material_input_from`` reference, produces a new immutable Step Portfolio view,
    and leaves every historical Step snapshot unchanged.
    """

    steps = list(result.steps)
    run = result.run

    for step_index, step in enumerate(run.workflow.steps):
        if not isinstance(step, DeriveStep):
            continue
        step_run = run.steps[step_index]
        if step_run.state is not StepRunState.PLANNED:
            raise UnsupportedDerivationError(
                f"derive step_index {step_index} must be planned before derivation"
            )
        reference = step_run.material_input_from
        if reference is None or reference.step_index >= step_index:
            raise UnsupportedDerivationError(
                f"derive step_index {step_index} must reference an earlier material Step"
            )
        try:
            source = steps[reference.step_index]
        except IndexError as exc:
            raise UnsupportedDerivationError(
                f"derive step_index {step_index} references unavailable material Step "
                f"{reference.step_index}"
            ) from exc

        steps[step_index] = derive_step_portfolios(
            step,
            source,
            step_index=step_index,
        )
        run = _mark_derive_succeeded(run, step_index)

    return WorkflowPortfolioResult(run=run, steps=tuple(steps))


__all__ = [
    "UnsupportedDerivationError",
    "derive_portfolio",
    "derive_step_portfolios",
    "derive_workflow_portfolios",
]
