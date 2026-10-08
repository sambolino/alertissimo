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

from dataclasses import dataclass, replace
import re
from typing import Literal

from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraph,
    EndpointCapability,
    semantic_record_noun_matches,
)
from alertissimo.data_layer.runtime.recipes import (
    CallValueSource, EncoderValueSource, RecipeCapability, StepValueSource,
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
    recipes: tuple[RecipeCapability, ...] = ()


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
    recipes: tuple[RecipeCapability, ...] = ()


def _cone_recipe_evidence(
    step: ConeSearchStep, graph: CapabilityGraph, source: Source | None,
) -> _CandidateEvidence | None:
    """Recipes own migrated providers; legacy tags cover only the others."""
    declared = graph.query_recipes(
        broker=source.broker if source else None,
        origin=source.origin if source else None,
        op=step.op,
    )
    if not declared:
        return None
    migrated = {(recipe.broker, recipe.origin) for recipe in declared}
    legacy = tuple(
        endpoint for endpoint in _raw_candidates_for_source(step, graph, source)
        if (endpoint.broker, endpoint.origin) not in migrated
    )
    endpoints = {
        (endpoint.broker, endpoint.origin, endpoint.endpoint): endpoint
        for endpoint in graph.endpoint_capabilities
    }
    feasible = []
    reasons = []
    raw = list(legacy)
    for recipe in declared:
        matching_calls = tuple(
            call for call in recipe.calls if call.required and any(
                semantic_record_noun_matches(output.semantic_record_type, step.semantic_type)
                for output in call.outputs
            )
        )
        if not matching_calls:
            continue
        raw.extend(endpoints[(recipe.broker, recipe.origin, call.endpoint)] for call in matching_calls)
        call = recipe.calls[0]
        if call not in matching_calls:
            reasons.append("cone discovery call must be required and map the requested record family")
            continue
        # Activate discovery followed by identity-bound retrievals. Independent
        # calls and dependencies on supplementary results need further evidence.
        if any(
            {parameter.source.call_index for parameter in later.params
             if isinstance(parameter.source, CallValueSource)} != {0}
            for later in recipe.calls[1:]
        ):
            reasons.append("cone follow-up calls must consume the discovery identities")
            continue
        paths = set()
        for parameter in call.params:
            value = parameter.source
            sources = (
                tuple(item for _, item in value.inputs)
                if isinstance(value, EncoderValueSource) else (value,)
            )
            paths.update(item.path for item in sources if isinstance(item, StepValueSource))
        if not {("ra",), ("dec",), ("radius",)} <= paths:
            reasons.append("cone recipe does not bind all canonical cone coordinates")
            continue
        unrepresented = tuple(
            field for field in ("magnitude_limit", "time_context")
            if getattr(step, field) is not None and (field,) not in paths
        )
        if unrepresented or step.criteria:
            reasons.append(f"cone inputs have no declared translation: {unrepresented or ('criteria',)}")
            continue
        feasible.append(recipe)
    compatible = legacy + tuple(
        endpoints[(recipe.broker, recipe.origin, recipe.calls[0].endpoint)]
        for recipe in feasible
    )
    return _CandidateEvidence(
        raw=tuple(raw), compatible=compatible, recipes=tuple(feasible),
        empty_status="deferred" if reasons else "unsupported",
        empty_reason="; ".join(dict.fromkeys(reasons)) or "no cone recipe produces the requested record family",
    )


def _lookup_recipe_evidence(
    step: LookupStep, graph: CapabilityGraph, source: Source | None,
) -> _CandidateEvidence | None:
    """Resolve the declared input namespace before considering output material."""
    declared = graph.query_recipes(
        broker=source.broker if source else None,
        origin=source.origin if source else None, op=step.op,
    )
    if not declared:
        return None
    migrated = {(recipe.broker, recipe.origin) for recipe in declared}
    legacy = tuple(
        endpoint for endpoint in _raw_candidates_for_source(step, graph, source)
        if (endpoint.broker, endpoint.origin) not in migrated
        and "target_id" in endpoint.binding_roles
    )
    endpoints = {
        (endpoint.broker, endpoint.origin, endpoint.endpoint): endpoint
        for endpoint in graph.endpoint_capabilities
    }
    choices = [(endpoint, None) for endpoint in legacy]
    raw = list(legacy)
    reasons = []
    for recipe in declared:
        if recipe.target_kind != step.target.kind:
            continue
        if recipe.target_kind != "object":
            reasons.append("alert lookup recipe activation is deferred pending physical identity evidence")
            continue
        call = recipe.calls[0]
        if not call.required or not any(
            semantic_record_noun_matches(output.semantic_record_type, "summary")
            and output.relative_field_path == "identity.object_id"
            for output in call.outputs
        ):
            continue
        endpoint = endpoints[(recipe.broker, recipe.origin, call.endpoint)]
        raw.append(endpoint)
        if len(recipe.calls) != 1:
            reasons.append("multi-call lookup recipe activation is deferred")
            continue
        if not any(
            isinstance(parameter.source, StepValueSource)
            and parameter.source.path == ("target", "ids")
            for parameter in call.params
        ) or "target_id" not in endpoint.binding_roles:
            reasons.append("lookup recipe does not bind the target identities")
            continue
        if any(isinstance(parameter.source, (CallValueSource, EncoderValueSource)) for parameter in call.params):
            reasons.append("lookup recipes require direct Step inputs")
            continue
        choices.append((endpoint, recipe))
    # Keep the existing singular/plural preference. Equal alternatives remain
    # ambiguous, including two recipes that resolve to the same physical endpoint.
    wants_collection = len(step.target.ids) > 1
    preferred = [
        choice for choice in choices
        if ("target_id" in choice[0].collection_binding_roles) == wants_collection
    ]
    choices = preferred or choices
    return _CandidateEvidence(
        raw=tuple(raw), compatible=tuple(endpoint for endpoint, _ in choices),
        recipes=tuple(recipe for _, recipe in choices if recipe is not None),
        empty_status="deferred" if reasons else "unsupported",
        empty_reason="; ".join(dict.fromkeys(reasons)) or "no lookup recipe supports the requested target kind and identity material",
    )


def _photometry_recipe_evidence(
    step: GetLightcurveStep | GetForcedPhotometryStep,
    graph: CapabilityGraph, source: Source | None,
) -> _CandidateEvidence | None:
    """Select declared retrievals; supplementary calls remain best effort."""
    declared = graph.query_recipes(
        broker=source.broker if source else None,
        origin=source.origin if source else None, op=step.op,
    )
    if not declared:
        return None
    migrated = {(recipe.broker, recipe.origin) for recipe in declared}
    legacy = tuple(
        endpoint for endpoint in _raw_candidates_for_source(step, graph, source)
        if (endpoint.broker, endpoint.origin) not in migrated
    )
    endpoints = {
        (endpoint.broker, endpoint.origin, endpoint.endpoint): endpoint
        for endpoint in graph.endpoint_capabilities
    }
    feasible, reasons = [], []
    raw = list(legacy)
    target_count = len(step.target.ids) if step.target is not None else None
    for recipe in declared:
        first = recipe.calls[0]
        # Forced measurements are mapped as detection/lightcurve material in the
        # current ontology. Their retrieval intent is the authored IR operation.
        if not first.required or not any(
            semantic_record_noun_matches(output.semantic_record_type, "lightcurve")
            for output in first.outputs
        ):
            continue
        raw.append(endpoints[(recipe.broker, recipe.origin, first.endpoint)])
        calls = []
        for call in recipe.calls:
            endpoint = endpoints[(recipe.broker, recipe.origin, call.endpoint)]
            paths = {
                parameter.source.path for parameter in call.params
                if isinstance(parameter.source, StepValueSource)
            }
            missing = tuple(
                name for name in ("bands", "time_context")
                if getattr(step, name) is not None and (name,) not in paths
            )
            reason = None
            if any(isinstance(parameter.source, (CallValueSource, EncoderValueSource)) for parameter in call.params):
                reason = "photometry recipes require direct Step inputs"
            elif ("target", "ids") not in paths or "target_id" not in endpoint.binding_roles:
                reason = "photometry recipe does not bind the target identities"
            elif missing:
                reason = f"photometry inputs have no declared translation: {missing}"
            elif (
                not call.required and target_count != 1
                and "target_id" not in endpoint.collection_binding_roles
            ):
                # Preserve the existing optional-supplement cardinality policy.
                # Required singular retrievals still use the binder's fan-out.
                reason = "optional photometry call lacks a collection target binding"
            if reason is not None:
                if call.required:
                    reasons.append(f"{recipe.broker}/{recipe.origin}/{call.endpoint}: {reason}")
                    break
                continue
            calls.append(call)
        else:
            feasible.append(replace(recipe, calls=tuple(calls)))
    return _CandidateEvidence(
        raw=tuple(raw), recipes=tuple(feasible),
        compatible=legacy + tuple(
            endpoints[(recipe.broker, recipe.origin, recipe.calls[0].endpoint)]
            for recipe in feasible
        ),
        empty_status="deferred" if reasons else "unsupported",
        empty_reason="; ".join(dict.fromkeys(reasons)) or "no photometry recipe maps lightcurve material",
    )


def _semantic_record_producer(semantic_record_type: str) -> str | None:
    _, at, qualifiers = semantic_record_type.partition("@")
    if not at:
        return None
    producer, _, _ = qualifiers.partition(":")
    return producer or None


def _classification_recipe_evidence(
    step: GetClassificationStep, graph: CapabilityGraph, source: Source | None,
) -> _CandidateEvidence | None:
    """Require targeted retrieval and authored translation of dynamic selectors."""
    declared = graph.query_recipes(
        broker=source.broker if source else None,
        origin=source.origin if source else None, op=step.op,
    )
    if not declared:
        return None
    migrated = {(recipe.broker, recipe.origin) for recipe in declared}
    legacy = tuple(
        endpoint for endpoint in _raw_candidates_for_source(step, graph, source)
        if (endpoint.broker, endpoint.origin) not in migrated
    )
    endpoints = {
        (endpoint.broker, endpoint.origin, endpoint.endpoint): endpoint
        for endpoint in graph.endpoint_capabilities
    }
    choices = [(endpoint, None) for endpoint in legacy]
    raw, reasons = list(legacy), []
    for recipe in declared:
        call = recipe.calls[0]
        outputs = tuple(
            output for output in call.outputs
            if semantic_record_noun_matches(output.semantic_record_type, "classification")
        )
        if not call.required or not outputs:
            continue
        endpoint = endpoints[(recipe.broker, recipe.origin, call.endpoint)]
        raw.append(endpoint)
        paths = {
            parameter.source.path for parameter in call.params
            if isinstance(parameter.source, StepValueSource)
        }
        if len(recipe.calls) != 1 or any(
            isinstance(parameter.source, (CallValueSource, EncoderValueSource))
            for parameter in call.params
        ):
            reasons.append("classification recipes require one call with direct Step inputs")
            continue
        if ("target", "ids") not in paths or "target_id" not in endpoint.binding_roles:
            reasons.append("classification recipe does not bind the target identities")
            continue
        if step.classifier is not None:
            producers = tuple(
                _semantic_record_producer(output.semantic_record_type) for output in outputs
            )
            exact = any(
                producer is not None and producer.lower() == step.classifier.lower()
                for producer in producers
            )
            dynamic = any(
                producer is not None and _DYNAMIC_QUALIFIER.fullmatch(producer)
                for producer in producers
            )
            translated = any(
                isinstance(parameter.source, StepValueSource)
                and parameter.source.path == ("classifier",)
                and parameter.parameter in endpoint.server_filters
                for parameter in call.params
            )
            if not exact and not (dynamic and translated):
                if dynamic:
                    reasons.append(
                        "requested classifier has only a dynamic producer mapping "
                        "without a declared server-filter translation"
                    )
                continue
        choices.append((endpoint, recipe))
    if step.target is not None and len(step.target.ids) > 1:
        collection = [
            choice for choice in choices
            if "target_id" in choice[0].collection_binding_roles
        ]
        choices = collection or choices
    return _CandidateEvidence(
        raw=tuple(raw), compatible=tuple(endpoint for endpoint, _ in choices),
        recipes=tuple(recipe for _, recipe in choices if recipe is not None),
        empty_status="deferred" if reasons else "unsupported",
        empty_reason="; ".join(dict.fromkeys(reasons)) or "no classification recipe maps the requested classifier",
    )


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


def _crossmatch_recipe_evidence(
    step: GetCrossmatchStep, graph: CapabilityGraph, source: Source | None,
) -> _CandidateEvidence | None:
    """Match catalog evidence before preferring a target collection encoding."""
    declared = graph.query_recipes(
        broker=source.broker if source else None,
        origin=source.origin if source else None, op=step.op,
    )
    if not declared:
        return None
    migrated = {(recipe.broker, recipe.origin) for recipe in declared}
    # Apply legacy compatibility per unmigrated provider. A migrated collection
    # alternative must not hide an unmigrated provider's singular retrieval.
    legacy_results = tuple(
        _legacy_candidate_evidence_for_source(step, graph, Source(broker=broker, origin=origin))
        for broker, origin in sorted({
            (endpoint.broker, endpoint.origin)
            for endpoint in _raw_candidates_for_source(step, graph, source)
            if (endpoint.broker, endpoint.origin) not in migrated
        })
    )
    legacy = tuple(endpoint for result in legacy_results for endpoint in result.compatible)
    endpoints = {
        (endpoint.broker, endpoint.origin, endpoint.endpoint): endpoint
        for endpoint in graph.endpoint_capabilities
    }
    choices = [(endpoint, None) for endpoint in legacy]
    raw = [endpoint for result in legacy_results for endpoint in result.raw]
    reasons = [
        result.empty_reason for result in legacy_results
        if not result.compatible and result.empty_status == "deferred" and result.empty_reason
    ]
    unsupported = [
        result.empty_reason for result in legacy_results
        if not result.compatible and result.empty_status == "unsupported" and result.empty_reason
    ]
    for recipe in declared:
        call = recipe.calls[0]
        if not call.required or not any(
            semantic_record_noun_matches(output.semantic_record_type, "crossmatch")
            for output in call.outputs
        ):
            continue
        endpoint = endpoints[(recipe.broker, recipe.origin, call.endpoint)]
        raw.append(endpoint)
        paths = {
            parameter.source.path for parameter in call.params
            if isinstance(parameter.source, StepValueSource)
        }
        if len(recipe.calls) != 1 or any(
            isinstance(parameter.source, (CallValueSource, EncoderValueSource))
            for parameter in call.params
        ):
            reasons.append("crossmatch recipes require one call with direct Step inputs")
            continue
        if ("target", "ids") not in paths or "target_id" not in endpoint.binding_roles:
            reasons.append("crossmatch recipe does not bind the target identities")
            continue
        if step.radius is not None:
            translated = any(
                isinstance(parameter.source, StepValueSource)
                and parameter.source.path == ("radius",)
                and parameter.parameter in endpoint.server_filters
                for parameter in call.params
            )
            if not translated:
                unsupported.append("no crossmatch recipe can honor the requested radius with a declared server-filter translation")
                continue
        if step.catalog is not None:
            relation = _crossmatch_catalog_relation(graph, endpoint, step.catalog)
            if relation == "dynamic":
                # Stored association rows can map a catalog name without
                # declaring a request that retrieves this particular catalog.
                reasons.append(
                    f"requested crossmatch catalog {step.catalog!r} has only a "
                    "dynamic producer mapping and cannot be confirmed statically"
                )
                continue
            if relation == "mismatch":
                unsupported.append(f"no crossmatch recipe produces requested catalog {step.catalog!r}")
                continue
        choices.append((endpoint, recipe))
    if step.target is not None and len(step.target.ids) > 1:
        collection = [
            choice for choice in choices
            if "target_id" in choice[0].collection_binding_roles
        ]
        choices = collection or choices
    return _CandidateEvidence(
        raw=tuple(raw), compatible=tuple(endpoint for endpoint, _ in choices),
        recipes=tuple(recipe for _, recipe in choices if recipe is not None),
        empty_status="deferred" if reasons else "unsupported",
        empty_reason="; ".join(dict.fromkeys(reasons or unsupported)) or "no crossmatch recipe maps the requested record family",
    )


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


def _product_recipe_evidence(
    step: GetCutoutStep | GetDataProductStep, graph: CapabilityGraph, source: Source | None,
) -> _CandidateEvidence | None:
    """Separate a bindable physical product call from mapped product material."""
    declared = graph.query_recipes(
        broker=source.broker if source else None,
        origin=source.origin if source else None, op=step.op,
    )
    if not declared:
        return None
    migrated = {(recipe.broker, recipe.origin) for recipe in declared}
    legacy = tuple(
        endpoint for endpoint in _legacy_candidate_evidence_for_source(step, graph, source).compatible
        if (endpoint.broker, endpoint.origin) not in migrated
    )
    endpoints = {
        (endpoint.broker, endpoint.origin, endpoint.endpoint): endpoint
        for endpoint in graph.endpoint_capabilities
    }
    # The existing staged candidate dependency supplies summary object IDs.
    # Alert IDs must be explicit; they cannot be inferred from an object view.
    target_kind = step.target.kind if step.target is not None else "object"
    choices = [(endpoint, None) for endpoint in legacy]
    raw = list(legacy)
    reasons = ["product target identity namespace is unspecified"] if target_kind is None else []
    for recipe in declared:
        if recipe.target_kind != target_kind:
            continue
        call = recipe.calls[0]
        endpoint = endpoints[(recipe.broker, recipe.origin, call.endpoint)]
        raw.append(endpoint)
        if not call.required or len(recipe.calls) != 1 or any(
            isinstance(parameter.source, (CallValueSource, EncoderValueSource))
            for parameter in call.params
        ):
            reasons.append("product recipes require one required call with direct Step inputs")
            continue
        if not any(
            isinstance(parameter.source, StepValueSource)
            and parameter.source.path == ("target", "ids")
            for parameter in call.params
        ) or "target_id" not in endpoint.binding_roles:
            reasons.append("product recipe does not bind the target identities")
            continue
        if recipe.target_kind == "alert":
            # Existing target_id normalization can complete summary object
            # identity. An alert ID must never become that object identity.
            reasons.append("alert product identity ownership lacks normalization evidence")
            continue
        if not any(
            semantic_record_noun_matches(output.semantic_record_type, "data_product")
            for output in call.outputs
        ):
            reasons.append("product recipe has no mapped data_product material")
            continue
        if endpoint.output_type not in {"object", "array"} or endpoint.output_format_params:
            # The normalizer's named JSON field mappings do not establish a
            # compatible shape for an image URL, binary FITS/AVRO, or a bare
            # image array. A mode/default cannot supply that missing evidence.
            reasons.append("product response shape/mode has no verified mapping compatibility")
            continue
        selectors = ("format", "size") if isinstance(step, GetCutoutStep) else ("product_type",)
        supplied = tuple(name for name in selectors if getattr(step, name) is not None)
        if supplied:
            reasons.append(f"product inputs lack verified response/selector compatibility: {supplied}")
            continue
        choices.append((endpoint, recipe))
    if step.target is not None and len(step.target.ids) > 1:
        collection = [
            choice for choice in choices
            if "target_id" in choice[0].collection_binding_roles
        ]
        choices = collection or choices
    return _CandidateEvidence(
        raw=tuple(raw), compatible=tuple(endpoint for endpoint, _ in choices),
        recipes=tuple(recipe for _, recipe in choices if recipe is not None),
        empty_status="deferred" if reasons else "unsupported",
        empty_reason="; ".join(dict.fromkeys(reasons)) or f"no product recipe accepts target kind {target_kind!r}",
    )


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
    if isinstance(step, (GetCutoutStep, GetDataProductStep)):
        recipes = _product_recipe_evidence(step, graph, source)
        if recipes is not None:
            return recipes
    if isinstance(step, GetCrossmatchStep):
        recipes = _crossmatch_recipe_evidence(step, graph, source)
        if recipes is not None:
            return recipes
    if isinstance(step, GetClassificationStep):
        recipes = _classification_recipe_evidence(step, graph, source)
        if recipes is not None:
            return recipes
    if isinstance(step, LookupStep):
        recipes = _lookup_recipe_evidence(step, graph, source)
        if recipes is not None:
            return recipes
    if isinstance(step, ConeSearchStep):
        recipes = _cone_recipe_evidence(step, graph, source)
        if recipes is not None:
            return recipes
    if isinstance(step, (GetLightcurveStep, GetForcedPhotometryStep)):
        recipes = _photometry_recipe_evidence(step, graph, source)
        if recipes is not None:
            return recipes
    return _legacy_candidate_evidence_for_source(step, graph, source)


def _legacy_candidate_evidence_for_source(
    step: Step, graph: CapabilityGraph, source: Source | None,
) -> _CandidateEvidence:
    """Compatibility checks for operation/source pairs not yet owned by recipes."""
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
        results.append(SourceCapabilityResult(
            source, status, candidates, reason, evidence.recipes,
        ))

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
