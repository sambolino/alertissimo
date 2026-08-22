"""Deterministically select registered endpoints for provider-facing IR steps.

Capability validation determines *what can* satisfy an intent; this planner chooses
endpoint identities, records predicate realization, and may prove either that a
later semantic retrieval can reuse an earlier candidate-search execution or that a
new invocation can be bound from an earlier semantic candidate view. WorkflowIR
Steps remain distinct in every case.
"""

from __future__ import annotations

import re

from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraph,
    EndpointCapability,
    canonical_semantic_noun,
)
from alertissimo.orchestration.ir.models import (
    DeriveStep,
    FilterStep,
    GetClassificationStep,
    GetCrossmatchStep,
    GetCutoutStep,
    GetDataProductStep,
    GetForcedPhotometryStep,
    GetLightcurveStep,
    GetSpectrumStep,
    GetStep,
    MatchStep,
    SearchStep,
    Source,
    Step,
    WorkflowIR,
)
from alertissimo.orchestration.ir.predicates import (
    BooleanPredicate,
    ComparisonPredicate,
    ExistsPredicate,
    NotPredicate,
    Predicate,
    SemanticReference,
)
from alertissimo.orchestration.runtime.models import (
    CandidateInputRef,
    EndpointPlan,
    EndpointPlanRef,
    StepRun,
    StepRunState,
    WorkflowRun,
)
from alertissimo.orchestration.validation import (
    CapabilityValidationResult,
    SourceCapabilityResult,
    validate_step_capabilities,
)

from .predicate_realization import realize_predicate


class PlanningError(ValueError):
    """Base class for failures to select a physical endpoint identity."""


class PlanningAmbiguityError(PlanningError):
    """Raised when selection would require an as-yet undefined ranking policy."""


class UnsupportedStepError(PlanningError):
    """Raised when registry capabilities cannot satisfy a provider-facing step."""


class PlanningDeferredError(PlanningError):
    """Raised when safe planning depends on capability semantics not yet modeled."""


class PlanningNotApplicableError(PlanningError):
    """Raised for a local/orchestration step that needs no provider endpoint."""


_DYNAMIC_QUALIFIER = re.compile(r"^\{[^{}]+\}$")


def _source_text(source: Source | None) -> str:
    if source is None:
        return "unconstrained"
    return f"broker={source.broker or '*'}, origin={source.origin or '*'}"


def _candidate_text(candidates: tuple[EndpointCapability, ...]) -> str:
    return ", ".join(
        f"{item.broker}/{item.origin}/{item.endpoint}" for item in candidates
    )


def _context(result: CapabilityValidationResult) -> str:
    semantic = (
        f", semantic_type={result.semantic_type!r}"
        if result.semantic_type is not None
        else ""
    )
    return f"operation={result.operation!r}{semantic}"


def _unsupported(result: CapabilityValidationResult) -> UnsupportedStepError:
    failures = "; ".join(
        f"{_source_text(item.source)}: {item.reason}"
        for item in result.source_results
        if item.status == "unsupported"
    )
    return UnsupportedStepError(
        f"unsupported provider step ({_context(result)}): {failures or result.reason}"
    )


def _select_one(
    result: CapabilityValidationResult, source_result: SourceCapabilityResult
) -> EndpointCapability:
    candidates = source_result.candidates
    if len(candidates) != 1:
        raise PlanningAmbiguityError(
            f"ambiguous provider endpoint ({_context(result)}, "
            f"source={_source_text(source_result.source)}); candidates: "
            f"{_candidate_text(candidates)}"
        )
    return candidates[0]


def _endpoint_plan(
    step: Step,
    endpoint: EndpointCapability,
    validation: CapabilityValidationResult,
    graph: CapabilityGraph,
) -> EndpointPlan:
    realization = None
    if isinstance(step, SearchStep) and step.predicate is not None:
        realization = realize_predicate(
            step.predicate,
            endpoint=endpoint,
            graph=graph,
        )
    return EndpointPlan(
        broker=endpoint.broker,
        origin=endpoint.origin,
        endpoint=endpoint.endpoint,
        semantic_type=validation.semantic_type,
        predicate_realization=realization,
    )


def _forced_photometry_supplement(
    step: GetLightcurveStep,
    primary: EndpointCapability,
    graph: CapabilityGraph,
) -> EndpointCapability | None:
    """Return one proven-compatible optional forced-photometry endpoint.

    ``GetLightcurveStep`` owns the semantic completeness policy; a forced endpoint
    is only a supplementary physical realization. The supplement is deliberately
    best-effort: absence, ambiguity, or target-cardinality incompatibility returns
    ``None`` rather than making the primary lightcurve plan fail.

    Bands and time windows are not auto-supplemented yet because the registry does
    not currently prove equivalent constraint semantics between ordinary history
    and forced-photometry endpoints. A targetless Step is treated conservatively as
    potentially multi-object, so only collection-capable forced endpoints qualify.
    """

    if step.bands is not None or step.time_context is not None:
        return None
    if "forced_photometry" in primary.operation_types:
        return None

    primary_identity = (primary.broker, primary.origin, primary.endpoint)
    candidates = tuple(
        endpoint
        for endpoint in graph.query_endpoints(
            broker=primary.broker,
            origin=primary.origin,
            operation_type="forced_photometry",
        )
        if (endpoint.broker, endpoint.origin, endpoint.endpoint) != primary_identity
        and "target_id" in endpoint.binding_roles
    )

    target_count = len(step.target.ids) if step.target is not None else None
    if target_count is None or target_count > 1:
        candidates = tuple(
            endpoint
            for endpoint in candidates
            if "target_id" in endpoint.collection_binding_roles
        )

    if len(candidates) != 1:
        return None
    return candidates[0]


def plan_step(step: Step, graph: CapabilityGraph) -> tuple[EndpointPlan, ...]:
    """Select provider endpoints and realize search predicates per endpoint."""
    validation = validate_step_capabilities(step, graph)
    if validation.status == "not_applicable":
        if isinstance(step, DeriveStep):
            return ()
        raise PlanningNotApplicableError(
            f"provider endpoint planning is not applicable ({_context(validation)}): "
            f"{validation.reason}"
        )
    if validation.status == "deferred":
        raise PlanningDeferredError(
            f"provider endpoint planning is deferred ({_context(validation)}): "
            f"{validation.reason}"
        )
    if validation.status == "unsupported":
        raise _unsupported(validation)

    selected = tuple(
        _select_one(validation, item) for item in validation.source_results
    )
    plans: list[EndpointPlan] = []
    for endpoint in selected:
        plans.append(_endpoint_plan(step, endpoint, validation, graph))
        if isinstance(step, GetLightcurveStep):
            supplement = _forced_photometry_supplement(step, endpoint, graph)
            if supplement is not None:
                plans.append(
                    _endpoint_plan(step, supplement, validation, graph).model_copy(
                        update={"required": False}
                    )
                )
    return tuple(plans)


def _semantic_record_producer(record_type: str) -> str | None:
    _, at, qualifiers = record_type.partition("@")
    if not at:
        return None
    producer, _, _ = qualifiers.partition(":")
    return producer or None


def _get_record_requirement(step: GetStep) -> SemanticReference | None:
    """Return the semantic record a targetless GetStep requires from candidates.

    This intentionally models only whole-record retrieval cases whose current Step
    fields add no extra retrieval semantics. More specific requests remain separate
    executions until their equivalence can be proved.
    """

    if getattr(step, "target", None) is not None:
        return None
    if isinstance(step, GetClassificationStep):
        return SemanticReference(
            semantic_type="classification",
            producer=step.classifier,
        )
    if isinstance(step, GetCrossmatchStep):
        if step.radius is not None:
            return None
        return SemanticReference(
            semantic_type="crossmatch",
            producer=step.catalog,
        )
    if isinstance(step, GetLightcurveStep):
        if step.bands is not None or step.time_context is not None:
            return None
        return SemanticReference(semantic_type="lightcurve")
    if isinstance(step, GetForcedPhotometryStep):
        if step.bands is not None or step.time_context is not None:
            return None
        return SemanticReference(semantic_type="forced_photometry")
    if isinstance(step, GetSpectrumStep):
        if step.time_context is not None:
            return None
        return SemanticReference(semantic_type="spectrum")
    if isinstance(step, GetDataProductStep):
        if step.product_type is not None:
            return None
        return SemanticReference(semantic_type="data_product")
    if isinstance(step, GetCutoutStep):
        return None
    return None


def _positive_references(predicate: Predicate | None) -> tuple[SemanticReference, ...]:
    """References whose existence is positively required by a predicate.

    AND preserves positive evidence. OR and NOT do not: neither proves that a
    particular referenced semantic record must be present in every accepted result.
    """

    if predicate is None:
        return ()
    if isinstance(predicate, ComparisonPredicate):
        return tuple(
            operand
            for operand in (predicate.left, predicate.right)
            if isinstance(operand, SemanticReference)
        )
    if isinstance(predicate, ExistsPredicate):
        return (predicate.reference,)
    if isinstance(predicate, BooleanPredicate) and predicate.operator == "and":
        return tuple(
            reference
            for operand in predicate.operands
            for reference in _positive_references(operand)
        )
    if isinstance(predicate, NotPredicate):
        return ()
    return ()


def _predicate_requires_reference(
    predicate: Predicate | None, requirement: SemanticReference
) -> bool:
    for reference in _positive_references(predicate):
        if reference.semantic_type != requirement.semantic_type:
            continue
        if requirement.producer is not None and reference.producer != requirement.producer:
            continue
        if requirement.channel is not None and reference.channel != requirement.channel:
            continue
        return True
    return False


def _search_execution_guarantees(
    search_step: SearchStep,
    search_plan: EndpointPlan,
    consumer_step: GetStep,
    consumer_plan: EndpointPlan,
    graph: CapabilityGraph,
) -> bool:
    requirement = _get_record_requirement(consumer_step)
    if requirement is None:
        return False
    if (
        search_plan.broker,
        search_plan.origin,
        search_plan.endpoint,
    ) != (
        consumer_plan.broker,
        consumer_plan.origin,
        consumer_plan.endpoint,
    ):
        return False

    records = graph.records_for_endpoint(
        search_plan.broker, search_plan.origin, search_plan.endpoint
    )
    matching = tuple(
        record
        for record in records
        if canonical_semantic_noun(record.semantic_record_type)
        == requirement.semantic_type
    )
    if not matching:
        return False

    if requirement.producer is None:
        return True

    for record in matching:
        producer = _semantic_record_producer(record.semantic_record_type)
        if producer == requirement.producer:
            return True
        if (
            producer is not None
            and _DYNAMIC_QUALIFIER.fullmatch(producer)
            and _predicate_requires_reference(search_step.predicate, requirement)
        ):
            return True
    return False


def _capability_for_plan(
    graph: CapabilityGraph, plan: EndpointPlan
) -> EndpointCapability:
    matches = tuple(
        endpoint
        for endpoint in graph.endpoint_capabilities
        if (
            endpoint.broker,
            endpoint.origin,
            endpoint.endpoint,
        ) == (
            plan.broker,
            plan.origin,
            plan.endpoint,
        )
    )
    if len(matches) != 1:
        raise PlanningDeferredError(
            "selected endpoint cannot be resolved uniquely in the capability graph: "
            f"{plan.broker}/{plan.origin}/{plan.endpoint}"
        )
    return matches[0]


def _can_bind_candidate_ids(
    search_step: SearchStep,
    consumer_plan: EndpointPlan,
    graph: CapabilityGraph,
) -> bool:
    endpoint = _capability_for_plan(graph, consumer_plan)
    if "target_id" not in endpoint.binding_roles:
        return False
    if "target_id" in endpoint.collection_binding_roles:
        return True
    return search_step.selection is not None and search_step.selection.latest == 1


def _mark_candidate_dependencies(
    workflow: WorkflowIR,
    planned_steps: tuple[StepRun, ...],
    graph: CapabilityGraph,
) -> tuple[StepRun, ...]:
    """Mark reuse, late binding, filtering, and matching over candidate views.

    The candidate population is created by a SearchStep and may be reduced by an
    explicit FilterStep or MatchStep. Provider GetSteps may materialize evidence
    used by a later local operation, but retrieval alone does not silently redefine
    the population. FilterStep consumes the latest materialized semantic view and
    keeps only candidates satisfying its unary predicate. MatchStep consumes the
    latest materialized semantic view and keeps only candidates participating in an
    accepted pairwise relation. Each filtering operation becomes the candidate owner
    for later targetless GetSteps.
    """

    rewritten = list(planned_steps)
    active_search_index: int | None = None
    current_candidate_index: int | None = None
    current_material_index: int | None = None

    for step_index, step in enumerate(workflow.steps):
        if isinstance(step, SearchStep):
            active_search_index = step_index
            current_candidate_index = step_index
            current_material_index = step_index
            continue

        if isinstance(step, FilterStep):
            if active_search_index is None or current_material_index is None:
                raise PlanningNotApplicableError(
                    f"filter step_index {step_index} requires an earlier materialized "
                    "candidate view"
                )
            rewritten[step_index] = rewritten[step_index].model_copy(
                update={
                    "candidate_input_from": CandidateInputRef(
                        step_index=current_material_index
                    )
                }
            )
            current_candidate_index = step_index
            current_material_index = step_index
            continue

        if isinstance(step, MatchStep):
            if active_search_index is None or current_material_index is None:
                raise PlanningNotApplicableError(
                    f"match step_index {step_index} requires an earlier materialized "
                    "candidate view"
                )
            rewritten[step_index] = rewritten[step_index].model_copy(
                update={
                    "candidate_input_from": CandidateInputRef(
                        step_index=current_material_index
                    )
                }
            )
            current_candidate_index = step_index
            current_material_index = step_index
            continue

        if active_search_index is None:
            continue

        if not isinstance(step, GetStep) or getattr(step, "target", None) is not None:
            active_search_index = None
            current_candidate_index = None
            current_material_index = None
            continue

        requirement = _get_record_requirement(step)
        if requirement is None:
            active_search_index = None
            current_candidate_index = None
            current_material_index = None
            continue

        search_step = workflow.steps[active_search_index]
        if not isinstance(search_step, SearchStep) or current_candidate_index is None:
            active_search_index = None
            current_candidate_index = None
            current_material_index = None
            continue

        search_run = rewritten[active_search_index]
        current_run = rewritten[step_index]
        current_plans: list[EndpointPlan] = []

        for consumer_plan in current_run.endpoint_plans:
            owner_index = None
            if current_candidate_index == active_search_index:
                owner_index = next(
                    (
                        plan_index
                        for plan_index, search_plan in enumerate(search_run.endpoint_plans)
                        if _search_execution_guarantees(
                            search_step,
                            search_plan,
                            step,
                            consumer_plan,
                            graph,
                        )
                    ),
                    None,
                )
            if owner_index is not None:
                current_plans.append(
                    consumer_plan.model_copy(
                        update={
                            "execution_reuse_from": EndpointPlanRef(
                                step_index=active_search_index,
                                plan_index=owner_index,
                            )
                        }
                    )
                )
                continue

            if not _can_bind_candidate_ids(search_step, consumer_plan, graph):
                endpoint = _capability_for_plan(graph, consumer_plan)
                cardinality = (
                    "a singular target binding"
                    if "target_id" in endpoint.binding_roles
                    else "no target_id binding"
                )
                raise PlanningDeferredError(
                    "candidate enrichment requires runtime binding from the current "
                    f"candidate identities, but {endpoint.broker}/{endpoint.origin}/"
                    f"{endpoint.endpoint} has {cardinality}; use a collection-capable "
                    "target endpoint or constrain candidate selection to latest 1"
                )

            current_plans.append(
                consumer_plan.model_copy(
                    update={
                        "candidate_input_from": CandidateInputRef(
                            step_index=current_candidate_index
                        )
                    }
                )
            )

        rewritten[step_index] = current_run.model_copy(
            update={"endpoint_plans": tuple(current_plans)}
        )
        current_material_index = step_index

    return tuple(rewritten)


def _same_forced_retrieval_input(
    owner_step: GetForcedPhotometryStep,
    owner_plan: EndpointPlan,
    lightcurve_step: GetLightcurveStep,
    supplement_plan: EndpointPlan,
) -> bool:
    """Prove that two forced-photometry plans address the same semantic input.

    Exact explicit targets are sufficient evidence. For targetless staged workflows,
    both plans must instead carry the same runtime candidate-input reference. Bands
    and time constraints must also match exactly; the current automatic supplement
    is unconstrained, so any constrained explicit forced Step cannot satisfy it.
    """

    if owner_step.bands != lightcurve_step.bands:
        return False
    if owner_step.time_context != lightcurve_step.time_context:
        return False

    owner_target = owner_step.target
    lightcurve_target = lightcurve_step.target
    if owner_target is not None or lightcurve_target is not None:
        return (
            owner_target is not None
            and lightcurve_target is not None
            and owner_target == lightcurve_target
        )

    return (
        owner_plan.candidate_input_from is not None
        and supplement_plan.candidate_input_from is not None
        and owner_plan.candidate_input_from == supplement_plan.candidate_input_from
    )


def _mark_equivalent_forced_reuse(
    workflow: WorkflowIR,
    planned_steps: tuple[StepRun, ...],
    graph: CapabilityGraph,
) -> tuple[StepRun, ...]:
    """Reuse earlier explicit forced retrievals for lightcurve supplements.

    The semantic occurrences remain distinct: an explicit
    ``GetForcedPhotometryStep`` still exposes its own Step output, and the later
    ``GetLightcurveStep`` still contains forced evidence as part of its completeness
    view. Only the physical call is coalesced. Reuse requires identical endpoint
    identity and positive proof of identical explicit targets or identical staged
    candidate input; endpoint coincidence alone is never sufficient.
    """

    rewritten = list(planned_steps)
    for step_index, step in enumerate(workflow.steps):
        if not isinstance(step, GetLightcurveStep):
            continue

        current_run = rewritten[step_index]
        current_plans = list(current_run.endpoint_plans)
        for plan_index, plan in enumerate(current_plans):
            if plan.execution_reuse_from is not None:
                continue
            capability = _capability_for_plan(graph, plan)
            if "forced_photometry" not in capability.operation_types:
                continue

            owner_reference: EndpointPlanRef | None = None
            for owner_step_index in range(step_index - 1, -1, -1):
                owner_step = workflow.steps[owner_step_index]
                if not isinstance(owner_step, GetForcedPhotometryStep):
                    continue
                owner_run = rewritten[owner_step_index]
                for owner_plan_index, owner_plan in enumerate(owner_run.endpoint_plans):
                    if (
                        owner_plan.broker,
                        owner_plan.origin,
                        owner_plan.endpoint,
                    ) != (plan.broker, plan.origin, plan.endpoint):
                        continue
                    if not _same_forced_retrieval_input(
                        owner_step,
                        owner_plan,
                        step,
                        plan,
                    ):
                        continue
                    owner_reference = EndpointPlanRef(
                        step_index=owner_step_index,
                        plan_index=owner_plan_index,
                    )
                    break
                if owner_reference is not None:
                    break

            if owner_reference is not None:
                current_plans[plan_index] = plan.model_copy(
                    update={
                        "execution_reuse_from": owner_reference,
                        "candidate_input_from": None,
                    }
                )

        rewritten[step_index] = current_run.model_copy(
            update={"endpoint_plans": tuple(current_plans)}
        )

    return tuple(rewritten)


def _plan_workflow_step(step: Step, graph: CapabilityGraph) -> tuple[EndpointPlan, ...]:
    """Plan one workflow occurrence, admitting orchestrated local steps."""

    if isinstance(step, (FilterStep, MatchStep)):
        return ()
    return plan_step(step, graph)


def plan_workflow(workflow: WorkflowIR, graph: CapabilityGraph) -> WorkflowRun:
    """Plan Steps, then mark candidate dependencies and proven execution reuse."""

    pending_run = WorkflowRun.from_workflow(workflow)
    planned_steps = tuple(
        StepRun(
            step_index=step_run.step_index,
            state=StepRunState.PLANNED,
            endpoint_plans=_plan_workflow_step(
                pending_run.step_at(step_run.step_index), graph
            ),
        )
        for step_run in pending_run.steps
    )
    planned_steps = _mark_candidate_dependencies(workflow, planned_steps, graph)
    planned_steps = _mark_equivalent_forced_reuse(workflow, planned_steps, graph)
    return WorkflowRun(workflow=workflow, steps=planned_steps)


__all__ = [
    "PlanningError",
    "PlanningAmbiguityError",
    "UnsupportedStepError",
    "PlanningDeferredError",
    "PlanningNotApplicableError",
    "plan_step",
    "plan_workflow",
]
