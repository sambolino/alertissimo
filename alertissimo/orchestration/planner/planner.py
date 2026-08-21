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
    return tuple(
        _endpoint_plan(step, item, validation, graph) for item in selected
    )


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
    """Mark reuse, late binding, and local filtering over candidate views.

    The candidate population is created by a SearchStep and changed only by an
    explicit FilterStep. Provider GetSteps may materialize evidence used by a later
    filter, but retrieval alone does not silently redefine the population. A filter
    consumes the latest materialized semantic view and becomes the new candidate
    population. Later targetless GetSteps bind from that filtered occurrence.
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
                raise PlanningDeferredError(
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


def _plan_workflow_step(step: Step, graph: CapabilityGraph) -> tuple[EndpointPlan, ...]:
    """Plan one workflow occurrence, admitting orchestrated local FilterSteps."""

    if isinstance(step, FilterStep):
        return ()
    return plan_step(step, graph)


def plan_workflow(workflow: WorkflowIR, graph: CapabilityGraph) -> WorkflowRun:
    """Plan Steps, then mark reuse or candidate-output dependencies."""

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
