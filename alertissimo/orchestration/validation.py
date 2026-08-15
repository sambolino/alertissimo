"""Read-only bridge from orchestration intent to registered capabilities.

The boundary is deliberately narrow::

    IR operation
        -> orchestration capability bridge
        -> CapabilityGraph
        -> candidate registered endpoint(s)

It answers whether and where the registered system can satisfy provider-facing
intent.  It does not select an endpoint, translate arguments, execute requests,
or merge results.  In particular, semantic-search criteria are not evidence of
server-side pushdown: this module validates only the broad registered operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraph,
    EndpointCapability,
)

from .ir.models import (
    ActionStep,
    AnalyzeStep,
    ConeSearchStep,
    FilterStep,
    GetClassificationStep,
    GetCrossmatchStep,
    GetCutoutStep,
    GetDataProductStep,
    GetForcedPhotometryStep,
    GetLightcurveStep,
    GetSpectrumStep,
    LightcurveStep,
    LookupStep,
    MatchStep,
    MonitorStep,
    SemanticSearchStep,
    Source,
    SqlQueryStep,
    Step,
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
_CLASSIFICATION_OPERATIONS = frozenset(
    {"classification_lookup", "object_classification"}
)
_GEOMETRIC_SEARCH_OPERATIONS = frozenset(
    {"cone_search", "spatial_search", "catalog_conesearch", "skymap_search"}
)


def _sources(step: Step) -> tuple[Source | None, ...]:
    # Each explicit source is checked independently so one successful broker
    # cannot hide another requested broker/origin that is unsupported.
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


def _candidates_for_source(
    step: Step, graph: CapabilityGraph, source: Source | None
) -> tuple[EndpointCapability, ...]:
    if isinstance(step, ConeSearchStep):
        return _query(graph, source, noun=step.semantic_type, operation="cone_search")
    if isinstance(step, SqlQueryStep):
        return _query(graph, source, noun=step.semantic_type, operation="sql_query")
    if isinstance(step, SemanticSearchStep):
        semantic = _query(graph, source, noun=step.semantic_type)
        return tuple(
            endpoint for endpoint in semantic
            if any(
                (op.endswith("_search") and op not in _GEOMETRIC_SEARCH_OPERATIONS)
                or op.endswith("_filter")
                for op in endpoint.operation_types
            )
        )
    if isinstance(step, GetLightcurveStep):
        return tuple(
            endpoint for endpoint in _query(graph, source)
            if _FULL_LIGHTCURVE_OPERATIONS.intersection(endpoint.operation_types)
        )
    if isinstance(step, GetForcedPhotometryStep):
        return _query(graph, source, operation="forced_photometry")
    if isinstance(step, GetClassificationStep):
        semantic = _query(graph, source, noun="classification")
        return tuple(
            endpoint for endpoint in semantic
            if _CLASSIFICATION_OPERATIONS.intersection(endpoint.operation_types)
        )
    if isinstance(step, GetCrossmatchStep):
        # Crossmatches can be embedded in a generically named context endpoint.
        return _query(graph, source, noun="crossmatch")
    if isinstance(step, GetCutoutStep):
        return _query(graph, source, operation="cutout")
    if isinstance(step, GetDataProductStep):
        return _query(graph, source, operation="data_product_lookup")
    if isinstance(step, GetSpectrumStep):
        # No operation vocabulary is guessed for an unregistered product.
        return ()
    return ()


def candidate_capabilities(
    step: Step, graph: CapabilityGraph
) -> tuple[EndpointCapability, ...]:
    """Discover all candidates without choosing among them."""
    keyed = {
        (item.broker, item.origin, item.endpoint): item
        for source in _sources(step)
        for item in _candidates_for_source(step, graph, source)
    }
    return tuple(keyed[key] for key in sorted(keyed))


def validate_step_capabilities(
    step: Step, graph: CapabilityGraph
) -> CapabilityValidationResult:
    """Validate one step against provider declarations without any I/O."""
    operation = getattr(step, "op", type(step).__name__)
    semantic_type = getattr(step, "semantic_type", None)

    if isinstance(step, LookupStep):
        results = []
        for source in _sources(step):
            endpoints = _query(graph, source)
            status: ValidationStatus = "deferred" if endpoints else "unsupported"
            reason = (
                "source exists; object-vs-alert capability resolution is deferred "
                "until identifier namespaces are resolved"
                if endpoints else "requested source has no registered endpoints"
            )
            results.append(SourceCapabilityResult(source, status, endpoints, reason))
        overall: ValidationStatus = (
            "unsupported" if any(item.status == "unsupported" for item in results)
            else "deferred"
        )
        return CapabilityValidationResult(
            operation, None, overall, tuple(results),
            "lookup target semantics cannot be inferred safely from the identifier",
        )

    if isinstance(step, (FilterStep, LightcurveStep, MatchStep, AnalyzeStep, ActionStep)):
        return CapabilityValidationResult(
            operation, semantic_type, "not_applicable", (),
            "provider CapabilityGraph validation does not govern this local/orchestration step",
        )
    if isinstance(step, MonitorStep):
        return CapabilityValidationResult(
            operation, semantic_type, "deferred", (),
            "stream transport capability is not modeled sufficiently in the registry",
        )

    results = []
    for source in _sources(step):
        candidates = _candidates_for_source(step, graph, source)
        status = "supported" if candidates else "unsupported"
        results.append(SourceCapabilityResult(
            source, status, candidates,
            "matching registered endpoint capability found" if candidates
            else "no compatible registered endpoint capability found",
        ))
    overall = (
        "supported" if results and all(item.status == "supported" for item in results)
        else "unsupported"
    )
    return CapabilityValidationResult(
        operation, semantic_type, overall, tuple(results),
        "all requested source constraints are supported" if overall == "supported"
        else "one or more requested source constraints are unsupported",
    )


def validate_workflow_capabilities(
    workflow: WorkflowIR, graph: CapabilityGraph
) -> tuple[CapabilityValidationResult, ...]:
    """Validate workflow steps in their deterministic declared order."""
    return tuple(validate_step_capabilities(step, graph) for step in workflow.steps)


__all__ = [
    "CapabilityValidationResult", "SourceCapabilityResult", "ValidationStatus",
    "candidate_capabilities", "validate_step_capabilities",
    "validate_workflow_capabilities",
]
