"""Read-only bridge from orchestration intent to registered capabilities.

The boundary is deliberately narrow::

    IR operation
        -> orchestration capability bridge
        -> CapabilityGraph
        -> candidate registered endpoint(s)

It answers whether and where the registered system can satisfy provider-facing
intent. It does not select an endpoint, translate arguments, execute requests,
or merge results. In particular, semantic-search criteria are not evidence of
server-side pushdown: this module validates the broad registered operation and
explicit semantic selectors such as a requested classifier or crossmatch catalog.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraph,
    EndpointCapability,
    semantic_record_noun_matches,
)
from alertissimo.orchestration.confirmation.capability import confirmation_endpoints

from .ir.models import (
    ActionStep,
    AnalyzeStep,
    ConeSearchStep,
    ConfirmStep,
    DeriveStep,
    FilterStep,
    GetClassificationStep,
    GetCrossmatchStep,
    GetCutoutStep,
    GetDataProductStep,
    GetForcedPhotometryStep,
    GetLightcurveStep,
    GetSpectrumStep,
    LookupStep,
    MatchStep,
    MonitorStep,
    SemanticSearchStep,
    Source,
    SqlQueryStep,
    Step,
    TargetSelector,
    WorkflowIR,
)

ValidationStatus = Literal["supported", "unsupported", "not_applicable", "deferred"]


@dataclass(frozen=True)
class SourceCapabilityResult:
    """Capability evidence for one explicit source (or the unconstrained space)."""

    source: Source | None
    status: ValidationStatus
    candidates: tuple[EndpointCapability, ...]
    reason: str


@dataclass(frozen=True)
class CapabilityValidationResult:
    """Explain provider-capability validation for a single IR step."""

    operation: str
    semantic_type: str | None
    status: ValidationStatus
    source_results: tuple[SourceCapabilityResult, ...]
    reason: str

    @property
    def candidates(self) -> tuple[EndpointCapability, ...]:
        """Return deterministic, de-duplicated candidates across source results."""
        keyed = {
            (item.broker, item.origin, item.endpoint): item
            for result in self.source_results
            for item in result.candidates
        }
        return tuple(keyed[key] for key in sorted(keyed))


_FULL_LIGHTCURVE_OPERATIONS = frozenset({"lightcurve", "lightcurve_lookup"})
_GEOMETRIC_SEARCH_OPERATIONS = frozenset(
    {"cone_search", "spatial_search", "catalog_conesearch", "skymap_search"}
)
_CROSSMATCH_RADIUS_OPERATIONS = frozenset({"crossmatch", "catalog_crossmatch"})
_DYNAMIC_QUALIFIER = re.compile(r"^\{[^{}]+\}$")


def _sources(step: Step) -> tuple[Source | None, ...]:
    return tuple(step.sources) if step.sources else (None,)


def _query(
    graph: CapabilityGraph,
    source: Source | None,
    *,
    noun: str | None = None,
    operation: str | None = None,
) -> tuple[EndpointCapability, ...]:
    return graph.query_endpoints(
        broker=source.broker if source else None,
        origin=source.origin if source else None,
        operation_type=operation,
        semantic_record_noun=noun,
    )


@dataclass(frozen=True)
class _CandidateEvidence:
    """Raw semantic matches and the subset compatible with the requested intent."""

    raw: tuple[EndpointCapability, ...]
    compatible: tuple[EndpointCapability, ...]
    empty_status: ValidationStatus = "unsupported"
    empty_reason: str | None = None


def _semantic_record_producer(semantic_record_type: str) -> str | None:
    _, at, qualifiers = semantic_record_type.partition("@")
    if not at:
        return None
    producer, _, _ = qualifiers.partition(":")
    return producer or None


def _classification_endpoint_supports_classifier(
    graph: CapabilityGraph,
    endpoint: EndpointCapability,
    classifier: str,
) -> bool:
    """Check exact/dynamic producer evidence for one classification endpoint."""

    requested = classifier.lower()
    records = (
        record
        for record in graph.records_for_endpoint(
            endpoint.broker, endpoint.origin, endpoint.endpoint
        )
        if semantic_record_noun_matches(record.semantic_record_type, "classification")
    )
    for record in records:
        producer = _semantic_record_producer(record.semantic_record_type)
        if producer is None:
            continue
        if producer.lower() == requested:
            return True
        if _DYNAMIC_QUALIFIER.fullmatch(producer) and (
            "classifier" in endpoint.server_filters or "classifier" in endpoint.params
        ):
            return True
    return False


def _crossmatch_catalog_relation(
    graph: CapabilityGraph,
    endpoint: EndpointCapability,
    catalog: str,
) -> Literal["exact", "dynamic", "mismatch"]:
    requested = catalog.lower()
    dynamic = False
    for record in graph.records_for_endpoint(
        endpoint.broker, endpoint.origin, endpoint.endpoint
    ):
        if not semantic_record_noun_matches(record.semantic_record_type, "crossmatch"):
            continue
        producer = _semantic_record_producer(record.semantic_record_type)
        if producer is None:
            continue
        if producer.lower() == requested:
            return "exact"
        if _DYNAMIC_QUALIFIER.fullmatch(producer):
            dynamic = True
    return "dynamic" if dynamic else "mismatch"


def _crossmatch_endpoint_honors_radius(endpoint: EndpointCapability) -> bool:
    return bool(
        _CROSSMATCH_RADIUS_OPERATIONS.intersection(endpoint.operation_types)
        and "radius" in endpoint.server_filters
    )


def _raw_candidates_for_source(
    step: Step, graph: CapabilityGraph, source: Source | None
) -> tuple[EndpointCapability, ...]:
    if isinstance(step, LookupStep):
        return _query(
            graph,
            source,
            operation=f"{step.target.kind}_lookup",
        )
    if isinstance(step, ConeSearchStep):
        semantic = _query(graph, source, noun=step.semantic_type)
        return tuple(
            endpoint
            for endpoint in semantic
            if _GEOMETRIC_SEARCH_OPERATIONS.intersection(endpoint.operation_types)
        )
    if isinstance(step, SqlQueryStep):
        return _query(graph, source, noun=step.semantic_type, operation="sql_query")
    if isinstance(step, SemanticSearchStep):
        semantic = _query(graph, source, noun=step.semantic_type)
        return tuple(
            endpoint
            for endpoint in semantic
            if any(
                (op.endswith("_search") and op not in _GEOMETRIC_SEARCH_OPERATIONS)
                or op.endswith("_filter")
                for op in endpoint.operation_types
            )
        )
    if isinstance(step, ConfirmStep):
        return confirmation_endpoints(
            graph,
            broker=source.broker if source else None,
            origin=source.origin if source else None,
            predicate=step.predicate,
        )
    if isinstance(step, GetLightcurveStep):
        return tuple(
            endpoint
            for endpoint in _query(graph, source)
            if _FULL_LIGHTCURVE_OPERATIONS.intersection(endpoint.operation_types)
        )
    if isinstance(step, GetForcedPhotometryStep):
        return _query(graph, source, operation="forced_photometry")
    if isinstance(step, GetClassificationStep):
        candidates = _query(graph, source, noun="classification")
        if step.classifier is None:
            return candidates
        return tuple(
            endpoint
            for endpoint in candidates
            if _classification_endpoint_supports_classifier(
                graph, endpoint, step.classifier
            )
        )
    if isinstance(step, GetCrossmatchStep):
        return _query(graph, source, noun="crossmatch")
    if isinstance(step, GetCutoutStep):
        return _query(graph, source, operation="cutout")
    if isinstance(step, GetDataProductStep):
        return _query(graph, source, operation="data_product_lookup")
    if isinstance(step, GetSpectrumStep):
        return ()
    return ()


def _candidate_evidence_for_source(
    step: Step, graph: CapabilityGraph, source: Source | None
) -> _CandidateEvidence:
    raw = _raw_candidates_for_source(step, graph, source)
    compatible = raw
    empty_status: ValidationStatus = "unsupported"
    empty_reason: str | None = None
    target = _target_selector(step)

    if isinstance(step, LookupStep):
        compatible = tuple(
            candidate
            for candidate in compatible
            if "target_id" in candidate.binding_roles
        )
        if raw and not compatible:
            empty_reason = (
                f"registered {step.target.kind}-lookup endpoints do not declare "
                "target_id binding"
            )

    if isinstance(step, GetCrossmatchStep):
        if target is not None:
            compatible = tuple(
                candidate
                for candidate in compatible
                if "target_id" in candidate.binding_roles
            )
            if raw and not compatible:
                empty_reason = (
                    "requested crossmatch target cannot be bound by any compatible endpoint"
                )

        if step.radius is not None and compatible:
            compatible = tuple(
                candidate
                for candidate in compatible
                if _crossmatch_endpoint_honors_radius(candidate)
            )
            if not compatible:
                empty_reason = (
                    "no registered crossmatch endpoint can honor the requested radius"
                )

    ids = target.ids if target is not None else None
    if compatible and ids is not None:
        if len(ids) == 1 and isinstance(step, LookupStep):
            singular = tuple(
                candidate
                for candidate in compatible
                if "target_id" not in candidate.collection_binding_roles
            )
            compatible = singular or compatible
        elif len(ids) > 1:
            collection = tuple(
                candidate
                for candidate in compatible
                if "target_id" in candidate.collection_binding_roles
            )
            # A singular endpoint remains semantically compatible: the binder
            # realizes the explicit plural target as one physical call per ID.
            compatible = collection or compatible

    if isinstance(step, GetCrossmatchStep) and step.catalog is not None and compatible:
        exact: list[EndpointCapability] = []
        dynamic: list[EndpointCapability] = []
        for candidate in compatible:
            relation = _crossmatch_catalog_relation(graph, candidate, step.catalog)
            if relation == "exact":
                exact.append(candidate)
            elif relation == "dynamic":
                dynamic.append(candidate)
        if exact:
            compatible = tuple(exact)
        elif dynamic:
            compatible = ()
            empty_status = "deferred"
            empty_reason = (
                f"requested crossmatch catalog {step.catalog!r} is represented only "
                "by a dynamic producer mapping and cannot be confirmed statically"
            )
        else:
            compatible = ()
            empty_reason = (
                f"no compatible endpoint produces crossmatch catalog {step.catalog!r}"
            )

    return _CandidateEvidence(
        raw=raw,
        compatible=compatible,
        empty_status=empty_status,
        empty_reason=empty_reason,
    )


def _target_selector(step: Step) -> TargetSelector | None:
    target = getattr(step, "target", None)
    return target if isinstance(target, TargetSelector) else None


def candidate_capabilities(
    step: Step, graph: CapabilityGraph
) -> tuple[EndpointCapability, ...]:
    keyed = {
        (item.broker, item.origin, item.endpoint): item
        for source in _sources(step)
        for item in _candidate_evidence_for_source(step, graph, source).compatible
    }
    return tuple(keyed[key] for key in sorted(keyed))


def validate_step_capabilities(
    step: Step, graph: CapabilityGraph
) -> CapabilityValidationResult:
    """Validate one step against provider declarations without any I/O."""
    operation = getattr(step, "op", type(step).__name__)
    semantic_type = getattr(step, "semantic_type", None)
    if isinstance(step, LookupStep):
        semantic_type = "summary" if step.target.kind == "object" else "detection"

    if isinstance(
        step,
        (FilterStep, DeriveStep, MatchStep, AnalyzeStep, ActionStep),
    ):
        return CapabilityValidationResult(
            operation,
            semantic_type,
            "not_applicable",
            (),
            "provider CapabilityGraph validation does not govern this local/orchestration step",
        )
    if isinstance(step, MonitorStep):
        return CapabilityValidationResult(
            operation,
            semantic_type,
            "deferred",
            (),
            "stream transport capability is not modeled sufficiently in the registry",
        )

    results = []
    for source in _sources(step):
        evidence = _candidate_evidence_for_source(step, graph, source)
        candidates = evidence.compatible
        target = _target_selector(step)
        status: ValidationStatus = "supported" if candidates else evidence.empty_status
        reason = (
            "matching registered endpoint capability found"
            if candidates
            else evidence.empty_reason
            or (
                "no compatible registered endpoint capability found"
            )
        )
        results.append(SourceCapabilityResult(source, status, candidates, reason))

    if any(item.status == "unsupported" for item in results):
        overall: ValidationStatus = "unsupported"
    elif any(item.status == "deferred" for item in results):
        overall = "deferred"
    else:
        overall = "supported"

    if overall == "supported":
        overall_reason = "all requested source constraints are supported"
    elif overall == "deferred":
        overall_reason = "one or more requested source constraints require deferred proof"
    else:
        overall_reason = "one or more requested source constraints are unsupported"

    return CapabilityValidationResult(
        operation,
        semantic_type,
        overall,
        tuple(results),
        overall_reason,
    )


def validate_workflow_capabilities(
    workflow: WorkflowIR, graph: CapabilityGraph
) -> tuple[CapabilityValidationResult, ...]:
    return tuple(validate_step_capabilities(step, graph) for step in workflow.steps)


__all__ = [
    "CapabilityValidationResult",
    "SourceCapabilityResult",
    "ValidationStatus",
    "candidate_capabilities",
    "validate_step_capabilities",
    "validate_workflow_capabilities",
]
