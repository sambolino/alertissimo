"""Lower declarative DSL surface intent into WorkflowIR plus result-view intent.

This is a semantic compiler boundary, not a planner. It preserves the scientist's
intent without selecting endpoints, binding provider parameters, or executing
anything. Scientific operations become ``WorkflowIR``; non-scientific presentation
instructions such as ``order by`` become a sibling ``ResultViewSpec``.
"""

from __future__ import annotations

from datetime import timedelta
import re
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from alertissimo.data_layer.runtime.capability_graph import CapabilityGraph
from alertissimo.orchestration.ir import (
    ClassifyStep,
    ColorColorStep,
    ColorMagnitudeStep,
    ConeSearchStep,
    ConfirmStep,
    FilterStep,
    GetClassificationStep,
    GetCrossmatchStep,
    GetCutoutStep,
    GetDataProductStep,
    GetForcedPhotometryStep,
    GetLightcurveStep,
    GetSpectrumStep,
    MatchStep,
    Predicate,
    SearchSelection,
    SemanticSearchStep,
    Source,
    TimeContext,
    WorkflowIR,
    and_predicates,
)
from alertissimo.orchestration.results import ResultOrderSpec, ResultViewSpec

from .capability_validation import (
    SurfaceCapabilityCheck,
    validate_surface_fragment_capabilities,
    validate_surface_capabilities,
)
from .fragment import fragment_surface_context
from .predicate_lowering import PredicateLoweringError, lower_expression_predicate
from .surface import (
    ConfirmClause,
    Duration,
    FilterClause,
    InsideClause,
    LatestClause,
    MatchClause,
    OrderByClause,
    RankedByClause,
    RequirementClause,
    SurfaceFragment,
    SurfaceScript,
    WhereClause,
    WithinClause,
)
from .validation import (
    extract_semantic_record_references,
    resolve_record_type,
    validate_surface_semantics,
)


class SurfaceLoweringError(ValueError):
    """A valid surface construct cannot yet be represented faithfully downstream."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        clause_index: int | None = None,
    ) -> None:
        self.code = code
        self.clause_index = clause_index
        location = f"clause {clause_index}: " if clause_index is not None else ""
        super().__init__(f"{location}{message} [{code}]")


class SurfaceCompilation(BaseModel):
    """Scientific workflow intent and orthogonal presentation intent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow: WorkflowIR
    view: ResultViewSpec = ResultViewSpec()


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
_IMPLICIT_GET_NOUNS = frozenset(
    {
        "classification",
        "crossmatch",
        "lightcurve",
        "forced_photometry",
        "cutout",
        "spectrum",
        "data_product",
    }
)


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


def _counterpart_source(origin: str, broker: str | None) -> Source:
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


def _first_filter_index(surface: SurfaceScript) -> int:
    return next(
        (
            index
            for index, clause in enumerate(surface.clauses)
            if isinstance(clause, FilterClause)
        ),
        len(surface.clauses),
    )


def _semantic_predicate(
    expression: str,
    *,
    record_types: frozenset[str],
    clause_index: int,
    scoped_noun: str | None = None,
    scoped_producer: str | None = None,
    scoped_channel: str | None = None,
) -> Predicate:
    try:
        return lower_expression_predicate(
            expression,
            record_types,
            scoped_noun=scoped_noun,
            scoped_producer=scoped_producer,
            scoped_channel=scoped_channel,
        )
    except PredicateLoweringError as exc:
        raise SurfaceLoweringError(
            str(exc),
            code="ungrounded_predicate",
            clause_index=clause_index,
        ) from exc


def _scoped_requirement_predicate(
    surface: SurfaceScript,
    clause: RequirementClause,
    *,
    noun: str,
    record_types: frozenset[str],
    clause_index: int,
) -> Predicate | None:
    predicates = [
        _semantic_predicate(
            expression,
            record_types=record_types,
            clause_index=clause_index,
            scoped_noun=noun,
            scoped_producer=clause.source,
            scoped_channel=clause.via or surface.candidates.broker,
        )
        for expression in clause.predicates
    ]
    return and_predicates(predicates)


def _candidate_search(
    surface: SurfaceScript,
    *,
    record_types: frozenset[str],
) -> tuple[SemanticSearchStep | ConeSearchStep, frozenset[int]]:
    """Compile candidate-scope constraints into one semantic search operation."""

    first_filter = _first_filter_index(surface)
    inside: tuple[int, InsideClause] | None = None
    within: tuple[int, WithinClause] | None = None
    latest: tuple[int, LatestClause] | None = None
    predicates: list[Predicate] = []
    consumed: set[int] = set()

    for index, clause in enumerate(surface.clauses[:first_filter]):
        if isinstance(clause, InsideClause):
            if inside is not None:
                raise SurfaceLoweringError(
                    "only one top-level inside constraint is currently supported",
                    code="multiple_inside_constraints",
                    clause_index=index,
                )
            inside = (index, clause)
            consumed.add(index)
        elif isinstance(clause, WithinClause):
            if within is not None:
                raise SurfaceLoweringError(
                    "only one top-level within constraint is currently supported",
                    code="multiple_time_constraints",
                    clause_index=index,
                )
            within = (index, clause)
            consumed.add(index)
        elif isinstance(clause, LatestClause):
            if latest is not None:
                raise SurfaceLoweringError(
                    "only one latest selector is currently supported",
                    code="multiple_latest_constraints",
                    clause_index=index,
                )
            latest = (index, clause)
            consumed.add(index)
        elif isinstance(clause, WhereClause):
            predicates.append(
                _semantic_predicate(
                    clause.condition,
                    record_types=record_types,
                    clause_index=index,
                )
            )
            consumed.add(index)
        elif isinstance(clause, RequirementClause) and clause.predicates:
            noun = resolve_record_type(clause.product, record_types)
            if noun is None:
                raise SurfaceLoweringError(
                    "scoped requirement must resolve to one ontology record type",
                    code="unresolved_requirement",
                    clause_index=index,
                )
            scoped = _scoped_requirement_predicate(
                surface,
                clause,
                noun=noun,
                record_types=record_types,
                clause_index=index,
            )
            if scoped is not None:
                predicates.append(scoped)

    predicate = and_predicates(predicates)
    time_context = (
        _time_context(within[1], clause_index=within[0]) if within is not None else None
    )
    selection = SearchSelection(latest=latest[1].count) if latest is not None else None
    sources = _candidate_sources(surface)

    if inside is not None:
        index, cone = inside
        return (
            ConeSearchStep(
                semantic_type="summary",
                predicate=predicate,
                selection=selection,
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
            predicate=predicate,
            selection=selection,
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


def _reject_method(clause: RequirementClause, *, clause_index: int) -> None:
    if clause.method is not None:
        raise SurfaceLoweringError(
            "this requirement cannot yet preserve an explicit producing method in its IR operation",
            code="unsupported_requirement_method",
            clause_index=clause_index,
        )


def _reject_producer(clause: RequirementClause, *, clause_index: int) -> None:
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
        return GetClassificationStep(
            sources=sources,
            classifier=clause.source,
        )

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
                "color-color lowering requires 'color-color <color-x> vs <color-y-field>'",
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

    params: dict[str, object] = {"candidate_origins": list(surface.candidates.origins)}
    sources: list[Source] = []

    if clause.counterpart_origin is not None:
        params["counterpart_origin"] = clause.counterpart_origin
        sources = [_counterpart_source(clause.counterpart_origin, effective_broker)]
    if clause.within is not None:
        params["max_time_delta"] = _duration(clause.within)
    if clause.on is not None:
        params["predicate"] = clause.on

    return MatchStep(sources=sources, params=params)


def _lower_confirm(
    surface: SurfaceScript,
    clause: ConfirmClause,
    *,
    predicate: Predicate | None = None,
) -> ConfirmStep:
    sources = [
        Source(origin=origin, broker=broker)
        for origin in surface.candidates.origins
        for broker in clause.brokers
    ]
    return ConfirmStep(
        sources=sources,
        predicate=predicate,
        required_agreement=clause.required_agreement,
    )


def _validate_semantics(surface: SurfaceScript, semantic_paths: _SemanticPaths) -> None:
    report = validate_surface_semantics(surface, semantic_paths=semantic_paths)
    if report.is_valid:
        return
    first = report.errors[0]
    raise SurfaceLoweringError(
        first.message,
        code=f"ontology_{first.code}",
        clause_index=first.clause_index,
    )


def _signature(
    noun: str,
    producer: str | None,
    channel: str | None,
) -> tuple[str, str | None, str | None]:
    return (
        noun,
        producer.lower() if producer else None,
        channel.lower() if channel else None,
    )


def _requirement_signature(
    surface: SurfaceScript,
    clause: RequirementClause,
    record_types: frozenset[str],
) -> tuple[str, str | None, str | None] | None:
    noun = resolve_record_type(clause.product, record_types)
    if noun is None:
        return None
    return _signature(noun, clause.source, clause.via or surface.candidates.broker)


def _implicit_requirements_from_where(
    surface: SurfaceScript,
    clause: WhereClause,
    *,
    record_types: frozenset[str],
) -> tuple[RequirementClause, ...]:
    requirements: list[RequirementClause] = []
    for ref in extract_semantic_record_references(clause.condition, record_types):
        if ref.noun == "summary" or ref.noun not in _IMPLICIT_GET_NOUNS:
            continue
        requirements.append(
            RequirementClause(
                product=ref.noun,
                source=ref.producer,
                via=ref.channel,
            )
        )
    return tuple(requirements)


def lower_surface(
    surface: SurfaceScript,
    *,
    semantic_paths: _SemanticPaths | None = None,
    name: str | None = None,
) -> SurfaceCompilation:
    """Lower ontology-valid surface intent into scientific IR plus view metadata."""

    semantic_model = semantic_paths or _semantic_path_model()
    _validate_semantics(surface, semantic_model)

    candidate_step, consumed = _candidate_search(
        surface,
        record_types=semantic_model.record_types,
    )
    steps = [candidate_step]
    first_filter = _first_filter_index(surface)
    emitted: set[tuple[str, str | None, str | None]] = set()
    view = ResultViewSpec()

    explicit_signatures = {
        signature
        for clause in surface.clauses
        if isinstance(clause, RequirementClause)
        for signature in [
            _requirement_signature(surface, clause, semantic_model.record_types)
        ]
        if signature is not None
    }

    for index, clause in enumerate(surface.clauses):
        if isinstance(clause, OrderByClause):
            view = ResultViewSpec(
                order_by=ResultOrderSpec(
                    expression=clause.expression,
                    direction=clause.direction,
                )
            )
            continue
        if index in consumed:
            adjacent_confirm = (
                index + 1 < len(surface.clauses)
                and isinstance(surface.clauses[index + 1], ConfirmClause)
            )
            if isinstance(clause, WhereClause) and not adjacent_confirm:
                for implied in _implicit_requirements_from_where(
                    surface,
                    clause,
                    record_types=semantic_model.record_types,
                ):
                    signature = _requirement_signature(
                        surface, implied, semantic_model.record_types
                    )
                    if signature is None or signature in emitted:
                        continue
                    if signature in explicit_signatures:
                        continue
                    steps.append(
                        _lower_requirement(
                            surface,
                            implied,
                            clause_index=index,
                            record_types=semantic_model.record_types,
                        )
                    )
                    emitted.add(signature)
            continue

        if isinstance(clause, RequirementClause):
            signature = _requirement_signature(
                surface, clause, semantic_model.record_types
            )
            if signature is None:
                raise SurfaceLoweringError(
                    "requirement must resolve to one ontology record type before lowering",
                    code="unresolved_requirement",
                    clause_index=index,
                )
            if signature not in emitted:
                steps.append(
                    _lower_requirement(
                        surface,
                        clause,
                        clause_index=index,
                        record_types=semantic_model.record_types,
                    )
                )
                emitted.add(signature)

            if clause.predicates and index >= first_filter:
                scoped = _scoped_requirement_predicate(
                    surface,
                    clause,
                    noun=signature[0],
                    record_types=semantic_model.record_types,
                    clause_index=index,
                )
                if scoped is not None:
                    steps.append(FilterStep(predicate=scoped))
        elif isinstance(clause, FilterClause):
            steps.append(
                FilterStep(
                    predicate=_semantic_predicate(
                        clause.condition,
                        record_types=semantic_model.record_types,
                        clause_index=index,
                    )
                )
            )
        elif isinstance(clause, ConfirmClause):
            attached_predicate = None
            if index > 0 and isinstance(surface.clauses[index - 1], WhereClause):
                previous = surface.clauses[index - 1]
                attached_predicate = _semantic_predicate(
                    previous.condition,
                    record_types=semantic_model.record_types,
                    clause_index=index - 1,
                )
            steps.append(
                _lower_confirm(
                    surface,
                    clause,
                    predicate=attached_predicate,
                )
            )
        elif isinstance(clause, MatchClause):
            steps.append(_lower_match(surface, clause, clause_index=index))
        elif isinstance(clause, RankedByClause):
            raise SurfaceLoweringError(
                "ranked by requires a registered ranking/score semantic before it can be lowered canonically",
                code="ranking_semantics_deferred",
                clause_index=index,
            )
        elif isinstance(clause, (InsideClause, WithinClause, LatestClause, WhereClause)):
            continue
        else:  # pragma: no cover - discriminated surface union guards this.
            raise SurfaceLoweringError(
                f"unsupported surface clause {type(clause).__name__}",
                code="unknown_surface_clause",
                clause_index=index,
            )

    return SurfaceCompilation(
        workflow=WorkflowIR(steps=steps, name=name),
        view=view,
    )


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
    if isinstance(clause, WhereClause):
        return False
    if not isinstance(clause, RequirementClause):
        return False
    noun = resolve_record_type(clause.product, record_types)
    return clause.method is not None or noun in _LOCAL_REQUIREMENTS


def compile_surface(
    surface: SurfaceScript,
    *,
    graph: CapabilityGraph | None = None,
    semantic_paths: _SemanticPaths | None = None,
    name: str | None = None,
) -> SurfaceCompilation:
    """Run ontology + capability validation and lower scientific/view intent."""

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

    return lower_surface(
        surface,
        semantic_paths=semantic_model,
        name=name,
    )


def compile_surface_fragment(
    fragment: SurfaceFragment,
    base_workflow: WorkflowIR,
    *,
    graph: CapabilityGraph | None = None,
    semantic_paths: _SemanticPaths | None = None,
    name: str | None = None,
) -> SurfaceCompilation:
    """Lower additional DSL clauses directly onto canonical WorkflowIR intent."""

    semantic_model = semantic_paths or _semantic_path_model()
    try:
        context = fragment_surface_context(fragment, base_workflow)
    except ValueError as error:
        raise SurfaceLoweringError(
            str(error),
            code="invalid_fragment_base_workflow",
        ) from error

    _validate_semantics(context, semantic_model)
    capability_report = validate_surface_fragment_capabilities(
        fragment,
        base_workflow,
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
            context,
            check,
            semantic_model.record_types,
        ):
            raise SurfaceLoweringError(
                check.reason,
                code="deferred_capability",
                clause_index=check.clause_index,
            )

    steps = list(base_workflow.steps)
    view = ResultViewSpec()
    for index, clause in enumerate(fragment.clauses):
        if isinstance(clause, OrderByClause):
            view = ResultViewSpec(
                order_by=ResultOrderSpec(
                    expression=clause.expression,
                    direction=clause.direction,
                )
            )
            continue
        if isinstance(clause, RequirementClause):
            step = _lower_requirement(
                context,
                clause,
                clause_index=index,
                record_types=semantic_model.record_types,
            )
            if step not in steps:
                steps.append(step)
            if clause.predicates:
                noun = resolve_record_type(clause.product, semantic_model.record_types)
                assert noun is not None
                scoped = _scoped_requirement_predicate(
                    context,
                    clause,
                    noun=noun,
                    record_types=semantic_model.record_types,
                    clause_index=index,
                )
                if scoped is not None:
                    steps.append(FilterStep(predicate=scoped))
            continue
        if isinstance(clause, FilterClause):
            steps.append(
                FilterStep(
                    predicate=_semantic_predicate(
                        clause.condition,
                        record_types=semantic_model.record_types,
                        clause_index=index,
                    )
                )
            )
            continue
        if isinstance(clause, ConfirmClause):
            steps.append(_lower_confirm(context, clause))
            continue
        if isinstance(clause, MatchClause):
            steps.append(_lower_match(context, clause, clause_index=index))
            continue
        if isinstance(clause, RankedByClause):
            raise SurfaceLoweringError(
                "ranked by requires a registered ranking/score semantic before it can be lowered canonically",
                code="ranking_semantics_deferred",
                clause_index=index,
            )
        raise SurfaceLoweringError(
            f"unsupported continuation clause {type(clause).__name__}",
            code="invalid_continuation_clause",
            clause_index=index,
        )

    return SurfaceCompilation(
        workflow=WorkflowIR(
            steps=steps,
            name=name if name is not None else base_workflow.name,
            description=base_workflow.description,
        ),
        view=view,
    )


def lower_surface_to_ir(
    surface: SurfaceScript,
    *,
    semantic_paths: _SemanticPaths | None = None,
    name: str | None = None,
) -> WorkflowIR:
    """Compatibility helper for callers that explicitly require WorkflowIR only.

    It refuses to discard an ``order by`` result-view instruction silently.
    """

    compilation = lower_surface(surface, semantic_paths=semantic_paths, name=name)
    if compilation.view.order_by is not None:
        raise SurfaceLoweringError(
            "surface contains result-view intent; use lower_surface() to preserve it",
            code="result_view_present",
        )
    return compilation.workflow


def compile_surface_to_ir(
    surface: SurfaceScript,
    *,
    graph: CapabilityGraph | None = None,
    semantic_paths: _SemanticPaths | None = None,
    name: str | None = None,
) -> WorkflowIR:
    """Compatibility helper for capability-checked WorkflowIR-only callers."""

    compilation = compile_surface(
        surface,
        graph=graph,
        semantic_paths=semantic_paths,
        name=name,
    )
    if compilation.view.order_by is not None:
        raise SurfaceLoweringError(
            "surface contains result-view intent; use compile_surface() to preserve it",
            code="result_view_present",
        )
    return compilation.workflow


__all__ = [
    "SurfaceCompilation",
    "SurfaceLoweringError",
    "compile_surface",
    "compile_surface_fragment",
    "compile_surface_to_ir",
    "lower_surface",
    "lower_surface_to_ir",
]
