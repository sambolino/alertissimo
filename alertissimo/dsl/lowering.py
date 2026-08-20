"""Lower the declarative DSL surface AST into orchestration ``WorkflowIR``.

This is a semantic compiler boundary, not a planner.  It preserves the user's
ordered intent in canonical IR operations without selecting endpoints, binding
provider parameters, or executing anything.  One surface clause may become zero,
one, or multiple IR operations; conversely, candidate-scope clauses may be folded
into the initial search operation.
"""

from __future__ import annotations

from datetime import timedelta
import re
from typing import Protocol

from pydantic import ValidationError

from alertissimo.data_layer.runtime.capability_graph import CapabilityGraph
from alertissimo.orchestration.ir import (
    ClassifyStep,
    ColorColorStep,
    ColorMagnitudeStep,
    ConeSearchStep,
    FilterStep,
    GetClassificationStep,
    GetCrossmatchStep,
    GetCutoutStep,
    GetDataProductStep,
    GetForcedPhotometryStep,
    GetLightcurveStep,
    GetSpectrumStep,
    LatestStep,
    MatchStep,
    OrderStep,
    SemanticSearchStep,
    Source,
    TimeContext,
    WorkflowIR,
)

from .capability_validation import (
    SurfaceCapabilityCheck,
    SurfaceCapabilityStatus,
    validate_surface_capabilities,
)
from .surface import (
    Duration,
    FilterClause,
    InsideClause,
    LatestClause,
    MatchClause,
    OrderByClause,
    RankedByClause,
    RequirementClause,
    SurfaceScript,
    WhereClause,
    WithinClause,
)
from .validation import resolve_record_type, validate_surface_semantics


class SurfaceLoweringError(ValueError):
    """A valid surface construct cannot yet be represented faithfully in IR."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        clause_index: int | None = None,
    ) -> None:
        self.code = code
        self.clause_index = clause_index
        location = (
            f"clause {clause_index}: " if clause_index is not None else ""
        )
        super().__init__(f"{location}{message} [{code}]")


class _SemanticPaths(Protocol):
    record_types: frozenset[str]

    def is_valid(self, semantic_path: str) -> bool: ...


_COLOR_MAGNITUDE_RE = re.compile(
    r"^color(?:[-_ ]?)magnitude\s+(?P<color>\S+)\s+vs\s+(?P<magnitude>\S+)$",
    re.IGNORECASE,
)
_COLOR_COLOR_RE = re.compile(
    r"^color(?:[-_ ]?)color\s+(?P<x>\S+)\s+vs\s+(?P<y>\S+)$",
    re.IGNORECASE,
)
_DURATION_SECONDS = {
    "s": 1.0,
    "min": 60.0,
    "h": 3600.0,
    "d": 86400.0,
    "w": 604800.0,
}
_ANGLE_TO_ARCSEC = {
    "arcsec": 1.0,
    "arcmin": 60.0,
    "deg": 3600.0,
}
_LOCAL_REQUIREMENTS = frozenset({"color_magnitude", "color_color"})


def _semantic_path_model() -> _SemanticPaths:
    from alertissimo.data_layer.semantic_model import SemanticPathModel

    return SemanticPathModel.from_ontology()


def _duration(value: Duration) -> timedelta:
    return timedelta(seconds=value.value * _DURATION_SECONDS[value.unit])


def _candidate_sources(
    surface: SurfaceScript,
    *,
    broker: str | None = None,
) -> list[Source]:
    effective_broker = broker if broker is not None else surface.candidates.broker
    return [
        Source(origin=origin, broker=effective_broker)
        if effective_broker is not None
        else Source(origin=origin)
        for origin in surface.candidates.origins
    ]


def _counterpart_source(
    origin: str,
    broker: str | None,
) -> Source:
    return (
        Source(origin=origin, broker=broker)
        if broker is not None
        else Source(origin=origin)
    )


def _time_context(clause: WithinClause, *, clause_index: int) -> TimeContext:
    if clause.duration is not None:
        return TimeContext(window=_duration(clause.duration), relative_to="now")
    try:
        return TimeContext.model_validate(
            {"start_time": clause.start, "end_time": clause.end}
        )
    except ValidationError as exc:
        raise SurfaceLoweringError(
            "explicit within bounds must currently be datetime-compatible values",
            code="invalid_time_window",
            clause_index=clause_index,
        ) from exc


def _radius_arcsec(clause: InsideClause, *, clause_index: int) -> float:
    unit = clause.radius.unit
    if unit is None:
        raise SurfaceLoweringError(
            "inside radius requires an explicit deg, arcmin, or arcsec unit for IR lowering",
            code="ambiguous_angle_unit",
            clause_index=clause_index,
        )
    return clause.radius.value * _ANGLE_TO_ARCSEC[unit]


def _candidate_search(
    surface: SurfaceScript,
) -> tuple[SemanticSearchStep | ConeSearchStep, frozenset[int]]:
    """Compile the candidate header plus its spatial/time preamble."""

    inside: tuple[int, InsideClause] | None = None
    within: tuple[int, WithinClause] | None = None
    consumed: set[int] = set()
    operational_seen = False

    for index, clause in enumerate(surface.clauses):
        if isinstance(clause, (InsideClause, WithinClause)):
            if operational_seen:
                raise SurfaceLoweringError(
                    "inside/within are candidate-scope constraints and must precede operational clauses",
                    code="late_candidate_constraint",
                    clause_index=index,
                )
            if isinstance(clause, InsideClause):
                if inside is not None:
                    raise SurfaceLoweringError(
                        "only one top-level inside constraint is currently supported",
                        code="multiple_inside_constraints",
                        clause_index=index,
                    )
                inside = (index, clause)
            else:
                if within is not None:
                    raise SurfaceLoweringError(
                        "only one top-level within constraint is currently supported",
                        code="multiple_time_constraints",
                        clause_index=index,
                    )
                within = (index, clause)
            consumed.add(index)
        else:
            operational_seen = True

    time_context = (
        _time_context(within[1], clause_index=within[0]) if within is not None else None
    )
    sources = _candidate_sources(surface)

    if inside is not None:
        index, cone = inside
        return (
            ConeSearchStep(
                semantic_type="summary",
                ra=cone.ra,
                dec=cone.dec,
                radius=_radius_arcsec(cone, clause_index=index),
                time_context=time_context,
                sources=sources,
            ),
            frozenset(consumed),
        )

    return (
        SemanticSearchStep(
            semantic_type="summary",
            criteria={},
            time_context=time_context,
            sources=sources,
        ),
        frozenset(consumed),
    )


def _normalized_product(product: str) -> str:
    return re.sub(r"[-\s]+", "_", product.strip().lower())


def _require_plain_product(
    clause: RequirementClause,
    noun: str,
    *,
    clause_index: int,
) -> None:
    if _normalized_product(clause.product) != noun:
        raise SurfaceLoweringError(
            f"details in {clause.product!r} need a product-specific lowering rule",
            code="unsupported_product_detail",
            clause_index=clause_index,
        )


def _reject_method(
    clause: RequirementClause,
    *,
    clause_index: int,
) -> None:
    if clause.method is not None:
        raise SurfaceLoweringError(
            "this requirement cannot yet preserve an explicit producing method in its IR operation",
            code="unsupported_requirement_method",
            clause_index=clause_index,
        )


def _reject_producer(
    clause: RequirementClause,
    *,
    clause_index: int,
) -> None:
    if clause.source is not None:
        raise SurfaceLoweringError(
            "this IR retrieval operation cannot yet preserve the requested semantic producer",
            code="unrepresentable_producer_constraint",
            clause_index=clause_index,
        )


def _lower_requirement(
    surface: SurfaceScript,
    clause: RequirementClause,
    *,
    clause_index: int,
    record_types: frozenset[str],
):
    noun = resolve_record_type(clause.product, record_types)
    if noun is None:
        raise SurfaceLoweringError(
            "requirement must resolve to one ontology record type before lowering",
            code="unresolved_requirement",
            clause_index=clause_index,
        )

    effective_broker = clause.via or surface.candidates.broker
    sources = _candidate_sources(surface, broker=effective_broker)

    if noun == "crossmatch":
        _require_plain_product(clause, noun, clause_index=clause_index)
        _reject_method(clause, clause_index=clause_index)
        return GetCrossmatchStep(sources=sources, catalog=clause.source)

    if noun == "classification":
        _require_plain_product(clause, noun, clause_index=clause_index)
        if clause.method is not None:
            if clause.source is not None or clause.via is not None:
                raise SurfaceLoweringError(
                    "classification using <method> is local in v0.1 and cannot also carry from/via qualifiers",
                    code="mixed_local_provider_classification",
                    clause_index=clause_index,
                )
            return ClassifyStep(method=clause.method)

        # The current GetClassificationStep has no producer field.  The common
        # producer==broker case is lossless through the physical Source constraint;
        # the rare cross-channel producer case remains intentionally postponed.
        if clause.source is not None and (
            effective_broker is None
            or clause.source.lower() != effective_broker.lower()
        ):
            raise SurfaceLoweringError(
                "classification producer differs from (or is more specific than) the physical broker; the current IR intentionally does not encode that rare extension",
                code="unrepresentable_classification_producer",
                clause_index=clause_index,
            )
        return GetClassificationStep(sources=sources)

    if noun == "lightcurve":
        _require_plain_product(clause, noun, clause_index=clause_index)
        _reject_method(clause, clause_index=clause_index)
        _reject_producer(clause, clause_index=clause_index)
        return GetLightcurveStep(sources=sources)

    if noun == "forced_photometry":
        _require_plain_product(clause, noun, clause_index=clause_index)
        _reject_method(clause, clause_index=clause_index)
        _reject_producer(clause, clause_index=clause_index)
        return GetForcedPhotometryStep(sources=sources)

    if noun == "cutout":
        _require_plain_product(clause, noun, clause_index=clause_index)
        _reject_method(clause, clause_index=clause_index)
        _reject_producer(clause, clause_index=clause_index)
        return GetCutoutStep(sources=sources)

    if noun == "spectrum":
        _require_plain_product(clause, noun, clause_index=clause_index)
        _reject_method(clause, clause_index=clause_index)
        _reject_producer(clause, clause_index=clause_index)
        return GetSpectrumStep(sources=sources)

    if noun == "data_product":
        _require_plain_product(clause, noun, clause_index=clause_index)
        _reject_method(clause, clause_index=clause_index)
        _reject_producer(clause, clause_index=clause_index)
        return GetDataProductStep(sources=sources)

    if noun == "color_magnitude":
        if clause.source is not None or clause.via is not None or clause.method is not None:
            raise SurfaceLoweringError(
                "color-magnitude is a local derivation in v0.1 and cannot carry from/via/using qualifiers",
                code="qualified_local_derivation",
                clause_index=clause_index,
            )
        match = _COLOR_MAGNITUDE_RE.fullmatch(clause.product.strip())
        if match is None:
            raise SurfaceLoweringError(
                "color-magnitude lowering requires 'color-magnitude <color> vs <magnitude-field>'",
                code="incomplete_color_magnitude",
                clause_index=clause_index,
            )
        return ColorMagnitudeStep(
            color=match.group("color"),
            magnitude_field=match.group("magnitude"),
        )

    if noun == "color_color":
        if clause.source is not None or clause.via is not None or clause.method is not None:
            raise SurfaceLoweringError(
                "color-color is a local derivation in v0.1 and cannot carry from/via/using qualifiers",
                code="qualified_local_derivation",
                clause_index=clause_index,
            )
        match = _COLOR_COLOR_RE.fullmatch(clause.product.strip())
        if match is None:
            raise SurfaceLoweringError(
                "color-color lowering requires 'color-color <color-x> vs <color-y>'",
                code="incomplete_color_color",
                clause_index=clause_index,
            )
        return ColorColorStep(
            color_x=match.group("x"),
            color_y=match.group("y"),
        )

    raise SurfaceLoweringError(
        f"ontology product {noun!r} has no canonical retrieval/derivation IR mapping yet",
        code="unmapped_requirement_type",
        clause_index=clause_index,
    )


def _lower_match(
    surface: SurfaceScript,
    clause: MatchClause,
    *,
    clause_index: int,
) -> MatchStep:
    effective_broker = clause.via or surface.candidates.broker
    if clause.via is not None and clause.counterpart_origin is None:
        raise SurfaceLoweringError(
            "match via <broker> requires an external 'from <origin>' counterpart in v0.1",
            code="match_via_without_counterpart",
            clause_index=clause_index,
        )

    params: dict[str, object] = {
        "candidate_origins": list(surface.candidates.origins),
    }
    sources: list[Source] = []

    if clause.counterpart_origin is not None:
        params["counterpart_origin"] = clause.counterpart_origin
        sources = [
            _counterpart_source(clause.counterpart_origin, effective_broker)
        ]
    if clause.within is not None:
        params["max_time_delta"] = _duration(clause.within)
    if clause.on is not None:
        params["predicate"] = clause.on

    return MatchStep(sources=sources, params=params)


def _validate_semantics(
    surface: SurfaceScript,
    semantic_paths: _SemanticPaths,
) -> None:
    report = validate_surface_semantics(surface, semantic_paths=semantic_paths)
    if report.is_valid:
        return
    first = report.errors[0]
    raise SurfaceLoweringError(
        first.message,
        code=f"ontology_{first.code}",
        clause_index=first.clause_index,
    )


def lower_surface_to_ir(
    surface: SurfaceScript,
    *,
    semantic_paths: _SemanticPaths | None = None,
    name: str | None = None,
) -> WorkflowIR:
    """Lower an ontology-valid surface AST into canonical ordered ``WorkflowIR``.

    Provider capability validation is deliberately a separate stage.  Use
    :func:`compile_surface_to_ir` when unsupported/deferred provider requirements
    should be rejected before lowering.
    """

    semantic_model = semantic_paths or _semantic_path_model()
    _validate_semantics(surface, semantic_model)

    candidate_step, consumed = _candidate_search(surface)
    steps = [candidate_step]

    for index, clause in enumerate(surface.clauses):
        if index in consumed:
            continue
        if isinstance(clause, (WhereClause, FilterClause)):
            steps.append(FilterStep(criteria={"expression": clause.condition}))
        elif isinstance(clause, LatestClause):
            steps.append(LatestStep(count=clause.count))
        elif isinstance(clause, RequirementClause):
            steps.append(
                _lower_requirement(
                    surface,
                    clause,
                    clause_index=index,
                    record_types=semantic_model.record_types,
                )
            )
        elif isinstance(clause, MatchClause):
            steps.append(_lower_match(surface, clause, clause_index=index))
        elif isinstance(clause, OrderByClause):
            steps.append(
                OrderStep(
                    expression=clause.expression,
                    direction=clause.direction,
                )
            )
        elif isinstance(clause, RankedByClause):
            raise SurfaceLoweringError(
                "ranked by requires a registered ranking/score semantic before it can be lowered canonically",
                code="ranking_semantics_deferred",
                clause_index=index,
            )
        else:  # pragma: no cover - discriminated surface union guards this.
            raise SurfaceLoweringError(
                f"unsupported surface clause {type(clause).__name__}",
                code="unknown_surface_clause",
                clause_index=index,
            )

    return WorkflowIR(steps=steps, name=name)


def _deferred_check_is_lowerable(
    surface: SurfaceScript,
    check: SurfaceCapabilityCheck,
    record_types: frozenset[str],
) -> bool:
    if check.subject == "match_local":
        return True
    if check.subject != "requirement" or check.clause_index is None:
        return False
    clause = surface.clauses[check.clause_index]
    if not isinstance(clause, RequirementClause):
        return False
    noun = resolve_record_type(clause.product, record_types)
    return clause.method is not None or noun in _LOCAL_REQUIREMENTS


def compile_surface_to_ir(
    surface: SurfaceScript,
    *,
    graph: CapabilityGraph | None = None,
    semantic_paths: _SemanticPaths | None = None,
    name: str | None = None,
) -> WorkflowIR:
    """Run ontology + capability validation and then lower to ``WorkflowIR``.

    Provider-facing capability uncertainty is never silently discarded.  Deferred
    local behavior that has an explicit IR representation (classification methods,
    color derivations, and local matching) may proceed; dynamic/unconfirmed
    provider capabilities remain a compile-time error.
    """

    semantic_model = semantic_paths or _semantic_path_model()
    _validate_semantics(surface, semantic_model)
    capability_report = validate_surface_capabilities(
        surface,
        graph=graph,
        semantic_paths=semantic_model,
    )

    if capability_report.unsupported:
        first = capability_report.unsupported[0]
        raise SurfaceLoweringError(
            first.reason,
            code="unsupported_capability",
            clause_index=first.clause_index,
        )

    for check in capability_report.deferred:
        if not _deferred_check_is_lowerable(
            surface,
            check,
            semantic_model.record_types,
        ):
            raise SurfaceLoweringError(
                check.reason,
                code="deferred_capability",
                clause_index=check.clause_index,
            )

    return lower_surface_to_ir(
        surface,
        semantic_paths=semantic_model,
        name=name,
    )


__all__ = [
    "SurfaceLoweringError",
    "compile_surface_to_ir",
    "lower_surface_to_ir",
]
