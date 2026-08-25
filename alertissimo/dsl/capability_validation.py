"""Read-only capability validation for the declarative DSL surface.

This module bridges an ontology-valid ``SurfaceScript`` to the existing
data-layer ``CapabilityGraph``. It never selects an endpoint, binds parameters,
executes providers, or lowers user intent to orchestration IR.
"""

from __future__ import annotations

from enum import Enum
import re
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraph,
    EndpointCapability,
    SemanticRecordCapability,
    build_capability_graph,
)
from alertissimo.orchestration.confirmation.capability import confirmation_endpoints
from alertissimo.orchestration.ir import WorkflowIR

from .predicate_lowering import PredicateLoweringError, lower_expression_predicate
from .fragment import fragment_surface_context
from .surface import (
    ConfirmClause,
    InsideClause,
    LookupCandidateSet,
    MatchClause,
    RankedByClause,
    RequirementClause,
    SurfaceFragment,
    SurfaceScript,
    WhereClause,
)
from .validation import (
    extract_semantic_record_references,
    resolve_record_type,
    validate_surface_semantics,
)


class SurfaceCapabilityValidationError(ValueError):
    """Raised when capability validation is attempted before ontology validity."""


class _SemanticPaths(Protocol):
    record_types: frozenset[str]

    def is_valid(self, semantic_path: str) -> bool: ...


class SurfaceCapabilityStatus(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    DEFERRED = "deferred"
    NOT_APPLICABLE = "not_applicable"


class SurfaceCapabilityEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    broker: str
    origin: str
    semantic_record_type: str | None = None
    endpoints: tuple[str, ...] = ()


class SurfaceCapabilityCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: Literal[
        "candidates",
        "requirement",
        "confirm",
        "match_counterpart",
        "match_local",
        "ranking",
    ]
    status: SurfaceCapabilityStatus
    reason: str
    clause_index: int | None = None
    origin: str | None = None
    broker: str | None = None
    semantic_noun: str | None = None
    producer: str | None = None
    channel: str | None = None
    evidence: tuple[SurfaceCapabilityEvidence, ...] = ()


class SurfaceCapabilityReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    checks: tuple[SurfaceCapabilityCheck, ...] = ()

    @property
    def unsupported(self) -> tuple[SurfaceCapabilityCheck, ...]:
        return tuple(
            check
            for check in self.checks
            if check.status is SurfaceCapabilityStatus.UNSUPPORTED
        )

    @property
    def deferred(self) -> tuple[SurfaceCapabilityCheck, ...]:
        return tuple(
            check
            for check in self.checks
            if check.status is SurfaceCapabilityStatus.DEFERRED
        )

    @property
    def status(self) -> SurfaceCapabilityStatus:
        if self.unsupported:
            return SurfaceCapabilityStatus.UNSUPPORTED
        if self.deferred:
            return SurfaceCapabilityStatus.DEFERRED
        if self.checks and all(
            check.status is SurfaceCapabilityStatus.NOT_APPLICABLE
            for check in self.checks
        ):
            return SurfaceCapabilityStatus.NOT_APPLICABLE
        return SurfaceCapabilityStatus.SUPPORTED

    @property
    def is_supported(self) -> bool:
        return self.status is SurfaceCapabilityStatus.SUPPORTED


_DYNAMIC_QUALIFIER = re.compile(r"^\{[^{}]+\}$")
_GEOMETRIC_SEARCH_OPERATIONS = frozenset(
    {"cone_search", "spatial_search", "catalog_conesearch", "skymap_search"}
)
_PROVIDER_OPERATION_FALLBACKS: dict[str, frozenset[str]] = {
    "lightcurve": frozenset({"lightcurve", "lightcurve_lookup"}),
    "data_product": frozenset({"data_product_lookup"}),
}
_LOCAL_REQUIREMENTS = frozenset({"color_magnitude", "color_color"})


def _semantic_path_model() -> _SemanticPaths:
    from alertissimo.data_layer.semantic_model import SemanticPathModel

    return SemanticPathModel.from_ontology()


def _semantic_record_parts(
    semantic_record_type: str,
) -> tuple[str, str | None, str | None]:
    noun, at, qualifiers = semantic_record_type.partition("@")
    if not at:
        return noun, None, None
    producer, colon, channel = qualifiers.partition(":")
    return noun, producer or None, (channel or None) if colon else None


def _is_dynamic_qualifier(value: str | None) -> bool:
    return bool(value and _DYNAMIC_QUALIFIER.fullmatch(value))


def _qualifier_relation(
    actual: str | None,
    requested: str | None,
    *,
    fallback: str | None = None,
) -> Literal["exact", "dynamic", "mismatch"]:
    if requested is None:
        return "exact"
    requested = requested.lower()
    if actual is None:
        actual = fallback
    if actual is None:
        return "mismatch"
    actual = actual.lower()
    if actual == requested:
        return "exact"
    if _is_dynamic_qualifier(actual):
        return "dynamic"
    return "mismatch"


def _record_relation(
    record: SemanticRecordCapability,
    *,
    producer: str | None,
    channel: str | None,
) -> Literal["exact", "dynamic", "mismatch"]:
    _, actual_producer, actual_channel = _semantic_record_parts(
        record.semantic_record_type
    )
    producer_relation = _qualifier_relation(actual_producer, producer)
    channel_relation = _qualifier_relation(
        actual_channel,
        channel,
        fallback=record.broker,
    )
    if "mismatch" in (producer_relation, channel_relation):
        return "mismatch"
    if "dynamic" in (producer_relation, channel_relation):
        return "dynamic"
    return "exact"


def _record_evidence(
    records: tuple[SemanticRecordCapability, ...],
) -> tuple[SurfaceCapabilityEvidence, ...]:
    return tuple(
        SurfaceCapabilityEvidence(
            broker=record.broker,
            origin=record.origin,
            semantic_record_type=record.semantic_record_type,
            endpoints=record.endpoints,
        )
        for record in sorted(
            records,
            key=lambda item: (
                item.broker,
                item.origin,
                item.semantic_record_type,
                item.endpoints,
            ),
        )
    )


def _endpoint_evidence(
    endpoints: tuple[EndpointCapability, ...],
) -> tuple[SurfaceCapabilityEvidence, ...]:
    grouped: dict[tuple[str, str], set[str]] = {}
    for endpoint in endpoints:
        grouped.setdefault((endpoint.broker, endpoint.origin), set()).add(
            endpoint.endpoint
        )
    return tuple(
        SurfaceCapabilityEvidence(
            broker=broker,
            origin=origin,
            endpoints=tuple(sorted(names)),
        )
        for (broker, origin), names in sorted(grouped.items())
    )


def _candidate_checks(
    surface: SurfaceScript,
    graph: CapabilityGraph,
) -> tuple[SurfaceCapabilityCheck, ...]:
    if isinstance(surface.candidates, LookupCandidateSet):
        candidates = surface.candidates
        endpoints = tuple(
            endpoint
            for endpoint in graph.query_endpoints(
                broker=candidates.broker,
                origin=candidates.origin,
                operation_type=f"{candidates.target_kind}_lookup",
            )
            if "target_id" in endpoint.binding_roles
        )
        if len(candidates.ids) == 1:
            singular = tuple(
                endpoint
                for endpoint in endpoints
                if "target_id" not in endpoint.collection_binding_roles
            )
            endpoints = singular or endpoints
        else:
            collection = tuple(
                endpoint
                for endpoint in endpoints
                if "target_id" in endpoint.collection_binding_roles
            )
            endpoints = collection or endpoints
        supported = bool(endpoints)
        return (
            SurfaceCapabilityCheck(
                subject="candidates",
                status=(
                    SurfaceCapabilityStatus.SUPPORTED
                    if supported
                    else SurfaceCapabilityStatus.UNSUPPORTED
                ),
                reason=(
                    f"registered {candidates.target_kind}-identifier lookup capability found"
                    if supported
                    else f"no registered {candidates.target_kind}-identifier lookup capability found"
                ),
                origin=candidates.origin,
                broker=candidates.broker,
                semantic_noun=(
                    "summary" if candidates.target_kind == "object" else "detection"
                ),
                channel=candidates.broker,
                evidence=_endpoint_evidence(endpoints),
            ),
        )

    spatial_required = any(
        isinstance(clause, InsideClause) for clause in surface.clauses
    )
    checks: list[SurfaceCapabilityCheck] = []
    for origin in surface.candidates.origins:
        endpoints = graph.query_endpoints(
            broker=surface.candidates.broker,
            origin=origin,
            semantic_record_noun="summary",
        )
        if spatial_required:
            endpoints = tuple(
                endpoint
                for endpoint in endpoints
                if _GEOMETRIC_SEARCH_OPERATIONS.intersection(
                    endpoint.operation_types
                )
            )
        supported = bool(endpoints)
        checks.append(
            SurfaceCapabilityCheck(
                subject="candidates",
                status=(
                    SurfaceCapabilityStatus.SUPPORTED
                    if supported
                    else SurfaceCapabilityStatus.UNSUPPORTED
                ),
                reason=(
                    "registered spatial-search object capability found"
                    if supported and spatial_required
                    else "no registered spatial-search object capability found"
                    if spatial_required
                    else "registered object-summary capability found"
                    if supported
                    else "no registered object-summary capability found"
                ),
                origin=origin,
                broker=surface.candidates.broker,
                semantic_noun="summary",
                channel=surface.candidates.broker,
                evidence=_endpoint_evidence(endpoints),
            )
        )
    return tuple(checks)


def _operation_fallback(
    graph: CapabilityGraph,
    *,
    noun: str,
    origin: str,
    broker: str | None,
    producer: str | None,
) -> tuple[EndpointCapability, ...]:
    operations = _PROVIDER_OPERATION_FALLBACKS.get(noun)
    if not operations:
        return ()
    if producer is not None and producer.lower() != origin.lower():
        return ()
    return tuple(
        endpoint
        for endpoint in graph.query_endpoints(broker=broker, origin=origin)
        if operations.intersection(endpoint.operation_types)
    )


def _dynamic_records_are_selectable(
    records: tuple[SemanticRecordCapability, ...],
    *,
    noun: str,
    graph: CapabilityGraph,
) -> bool:
    if noun != "classification":
        return False
    endpoint_keys = {
        (record.broker, record.origin, endpoint)
        for record in records
        for endpoint in record.endpoints
    }
    return any(
        (endpoint.broker, endpoint.origin, endpoint.endpoint) in endpoint_keys
        and ("classifier" in endpoint.server_filters or "classifier" in endpoint.params)
        for endpoint in graph.endpoint_capabilities
    )


def _requirement_checks(
    surface: SurfaceScript,
    clause: RequirementClause,
    *,
    clause_index: int,
    graph: CapabilityGraph,
    record_types: frozenset[str],
) -> tuple[SurfaceCapabilityCheck, ...]:
    noun = resolve_record_type(clause.product, record_types)
    if noun is None:
        raise SurfaceCapabilityValidationError(
            "capability validation requires ontology-valid requirement nouns"
        )

    broker = clause.via or surface.candidates.broker
    channel = broker

    if clause.method is not None:
        return tuple(
            SurfaceCapabilityCheck(
                subject="requirement",
                status=SurfaceCapabilityStatus.DEFERRED,
                reason=(
                    "an explicit producing method was requested; local/algorithm "
                    "capabilities are not modeled by the provider CapabilityGraph"
                ),
                clause_index=clause_index,
                origin=origin,
                broker=broker,
                semantic_noun=noun,
                producer=clause.source,
                channel=channel,
            )
            for origin in surface.candidates.origins
        )

    checks: list[SurfaceCapabilityCheck] = []
    for origin in surface.candidates.origins:
        records = graph.query_records(
            broker=broker,
            origin=origin,
            semantic_record_noun=noun,
        )
        exact = tuple(
            record
            for record in records
            if _record_relation(
                record,
                producer=clause.source,
                channel=channel,
            )
            == "exact"
        )
        dynamic = tuple(
            record
            for record in records
            if _record_relation(
                record,
                producer=clause.source,
                channel=channel,
            )
            == "dynamic"
        )

        if exact:
            status = SurfaceCapabilityStatus.SUPPORTED
            reason = "exact registered semantic-record capability found"
            evidence = _record_evidence(exact)
        else:
            endpoints = _operation_fallback(
                graph,
                noun=noun,
                origin=origin,
                broker=broker,
                producer=clause.source,
            )
            if endpoints:
                status = SurfaceCapabilityStatus.SUPPORTED
                reason = (
                    "registered provider operation can satisfy the product even "
                    "though no first-level semantic record is materialized directly"
                )
                evidence = _endpoint_evidence(endpoints)
            elif dynamic and _dynamic_records_are_selectable(
                dynamic, noun=noun, graph=graph
            ):
                status = SurfaceCapabilityStatus.SUPPORTED
                reason = (
                    "dynamic semantic producer is backed by an explicit provider "
                    "selector for this record family"
                )
                evidence = _record_evidence(dynamic)
            elif dynamic:
                status = SurfaceCapabilityStatus.DEFERRED
                reason = (
                    "only a dynamic qualified semantic capability is registered; "
                    "the requested producer/channel cannot be confirmed statically"
                )
                evidence = _record_evidence(dynamic)
            elif noun in _LOCAL_REQUIREMENTS:
                status = SurfaceCapabilityStatus.DEFERRED
                reason = (
                    "the product is locally derivable, but local derivation/input "
                    "capabilities are outside the provider CapabilityGraph"
                )
                evidence = ()
            else:
                status = SurfaceCapabilityStatus.UNSUPPORTED
                reason = "no compatible registered capability found"
                evidence = ()

        checks.append(
            SurfaceCapabilityCheck(
                subject="requirement",
                status=status,
                reason=reason,
                clause_index=clause_index,
                origin=origin,
                broker=broker,
                semantic_noun=noun,
                producer=clause.source,
                channel=channel,
                evidence=evidence,
            )
        )
    return tuple(checks)


def _adjacent_confirm_predicate(
    surface: SurfaceScript,
    *,
    clause_index: int,
    record_types: frozenset[str],
):
    if clause_index == 0 or not isinstance(surface.clauses[clause_index - 1], WhereClause):
        return None
    where = surface.clauses[clause_index - 1]
    try:
        return lower_expression_predicate(where.condition, record_types)
    except PredicateLoweringError as exc:  # semantic validation should normally guard this
        raise SurfaceCapabilityValidationError(
            f"cannot lower adjacent where predicate for confirmation: {exc}"
        ) from exc


def _confirm_checks(
    surface: SurfaceScript,
    clause: ConfirmClause,
    *,
    clause_index: int,
    graph: CapabilityGraph,
    record_types: frozenset[str],
) -> tuple[SurfaceCapabilityCheck, ...]:
    predicate = _adjacent_confirm_predicate(
        surface,
        clause_index=clause_index,
        record_types=record_types,
    )
    checks: list[SurfaceCapabilityCheck] = []
    for origin in surface.candidates.origins:
        for broker in clause.brokers:
            endpoints = confirmation_endpoints(
                graph,
                broker=broker,
                origin=origin,
                predicate=predicate,
            )
            supported = bool(endpoints)
            if predicate is None:
                positive_reason = "registered target-bindable object evidence capability found"
                negative_reason = "no registered target-bindable object evidence capability found"
                semantic_noun = "summary"
            else:
                positive_reason = "registered target-bindable proposition evidence capability found"
                negative_reason = "no target-bindable endpoint can materialize the confirmed proposition"
                semantic_noun = None
            checks.append(
                SurfaceCapabilityCheck(
                    subject="confirm",
                    status=(
                        SurfaceCapabilityStatus.SUPPORTED
                        if supported
                        else SurfaceCapabilityStatus.UNSUPPORTED
                    ),
                    reason=positive_reason if supported else negative_reason,
                    clause_index=clause_index,
                    origin=origin,
                    broker=broker,
                    semantic_noun=semantic_noun,
                    channel=broker,
                    evidence=_endpoint_evidence(endpoints),
                )
            )
    return tuple(checks)


def _match_checks(
    surface: SurfaceScript,
    clause: MatchClause,
    *,
    clause_index: int,
    graph: CapabilityGraph,
) -> tuple[SurfaceCapabilityCheck, ...]:
    checks: list[SurfaceCapabilityCheck] = []
    broker = clause.via or surface.candidates.broker
    if clause.counterpart_origin is not None:
        endpoints = graph.query_endpoints(
            broker=broker,
            origin=clause.counterpart_origin,
        )
        checks.append(
            SurfaceCapabilityCheck(
                subject="match_counterpart",
                status=(
                    SurfaceCapabilityStatus.SUPPORTED
                    if endpoints
                    else SurfaceCapabilityStatus.UNSUPPORTED
                ),
                reason=(
                    "registered counterpart source capability found"
                    if endpoints
                    else "no registered counterpart source capability found"
                ),
                clause_index=clause_index,
                origin=clause.counterpart_origin,
                broker=broker,
                channel=broker,
                evidence=_endpoint_evidence(endpoints),
            )
        )

    checks.append(
        SurfaceCapabilityCheck(
            subject="match_local",
            status=SurfaceCapabilityStatus.DEFERRED,
            reason=(
                "association is local orchestration behavior; executable match "
                "methods/predicates are not modeled by the provider CapabilityGraph"
            ),
            clause_index=clause_index,
            broker=broker,
        )
    )
    return tuple(checks)


def validate_surface_capabilities(
    surface: SurfaceScript,
    *,
    graph: CapabilityGraph | None = None,
    semantic_paths: _SemanticPaths | None = None,
) -> SurfaceCapabilityReport:
    """Validate provider-facing surface intent against registered capabilities."""

    semantic_model = semantic_paths or _semantic_path_model()
    semantic_report = validate_surface_semantics(
        surface,
        semantic_paths=semantic_model,
    )
    if not semantic_report.is_valid:
        codes = ", ".join(issue.code for issue in semantic_report.errors)
        raise SurfaceCapabilityValidationError(
            "capability validation requires ontology-valid surface intent"
            + (f" ({codes})" if codes else "")
        )

    capability_graph = graph or build_capability_graph()
    checks: list[SurfaceCapabilityCheck] = list(
        _candidate_checks(surface, capability_graph)
    )
    checked_requirements: set[tuple[str, str | None, str | None]] = set()

    for index, clause in enumerate(surface.clauses):
        if isinstance(clause, RequirementClause):
            noun = resolve_record_type(clause.product, semantic_model.record_types)
            signature = (
                noun or clause.product,
                clause.source,
                clause.via or surface.candidates.broker,
            )
            if signature in checked_requirements:
                continue
            checked_requirements.add(signature)
            checks.extend(
                _requirement_checks(
                    surface,
                    clause,
                    clause_index=index,
                    graph=capability_graph,
                    record_types=semantic_model.record_types,
                )
            )
        elif isinstance(clause, WhereClause):
            for ref in extract_semantic_record_references(
                clause.condition, semantic_model.record_types
            ):
                signature = (
                    ref.noun,
                    ref.producer,
                    ref.channel or surface.candidates.broker,
                )
                if signature in checked_requirements:
                    continue
                checked_requirements.add(signature)
                checks.extend(
                    _requirement_checks(
                        surface,
                        RequirementClause(
                            product=ref.noun,
                            source=ref.producer,
                            via=ref.channel,
                        ),
                        clause_index=index,
                        graph=capability_graph,
                        record_types=semantic_model.record_types,
                    )
                )
        elif isinstance(clause, ConfirmClause):
            checks.extend(
                _confirm_checks(
                    surface,
                    clause,
                    clause_index=index,
                    graph=capability_graph,
                    record_types=semantic_model.record_types,
                )
            )
        elif isinstance(clause, MatchClause):
            checks.extend(
                _match_checks(
                    surface,
                    clause,
                    clause_index=index,
                    graph=capability_graph,
                )
            )
        elif isinstance(clause, RankedByClause):
            checks.append(
                SurfaceCapabilityCheck(
                    subject="ranking",
                    status=SurfaceCapabilityStatus.DEFERRED,
                    reason=(
                        "ranking methods are not yet registered as local/provider "
                        "capabilities"
                    ),
                    clause_index=index,
                )
            )

    return SurfaceCapabilityReport(checks=tuple(checks))


def validate_surface_fragment_capabilities(
    fragment: SurfaceFragment,
    base_workflow: WorkflowIR,
    *,
    graph: CapabilityGraph | None = None,
    semantic_paths: _SemanticPaths | None = None,
) -> SurfaceCapabilityReport:
    """Validate only newly requested capabilities against canonical IR context."""

    context = fragment_surface_context(fragment, base_workflow)
    report = validate_surface_capabilities(
        context,
        graph=graph,
        semantic_paths=semantic_paths,
    )
    return SurfaceCapabilityReport(
        checks=tuple(check for check in report.checks if check.subject != "candidates")
    )


__all__ = [
    "SurfaceCapabilityCheck",
    "SurfaceCapabilityEvidence",
    "SurfaceCapabilityReport",
    "SurfaceCapabilityStatus",
    "SurfaceCapabilityValidationError",
    "validate_surface_capabilities",
    "validate_surface_fragment_capabilities",
]
