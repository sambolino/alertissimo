"""Deterministically select registered endpoints for provider-facing IR steps.

Capability validation determines *what can* satisfy an intent; this planner chooses
endpoint identities, records predicate realization, and may prove either that a
later semantic retrieval can reuse an earlier candidate-search execution or that a
new invocation can be bound from an earlier semantic candidate view. WorkflowIR
Steps remain distinct in every case.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from alertissimo.data_layer.runtime.recipes import (
    CallValueSource, ConstantValueSource, EncoderValueSource, RecipeCall, RecipeCapability,
    StepValueSource,
)

from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraph,
    EndpointCapability,
    RequestConstraintCapability,
    canonical_semantic_noun,
)
from alertissimo.orchestration.ir.models import (
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
    GetStep,
    LookupStep,
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
    MaterialInputRef,
    PlanCandidateInputRef,
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
        recipes = ", ".join(
            f"{recipe.broker}/{recipe.origin}/recipe[{recipe.alternative_index}]"
            for recipe in source_result.recipes
        )
        raise PlanningAmbiguityError(
            f"ambiguous provider endpoint ({_context(result)}, "
            f"source={_source_text(source_result.source)}); candidates: "
            f"{_candidate_text(candidates)}" + (f"; recipes: {recipes}" if recipes else "")
        )
    return candidates[0]


def _recipe_assignments(call: RecipeCall, *, plan_offset: int, step: Step) -> dict:
    """Carry value sources to the binder; never encode values during planning."""
    def physical_literal(value):
        if isinstance(value, Mapping):
            return {key: physical_literal(item) for key, item in value.items()}
        if isinstance(value, tuple):
            return [physical_literal(item) for item in value]
        return value

    sources, constants = {}, {}
    if isinstance(step, SearchStep) and step.selection is not None and call.latest_selection is not None:
        constants.update({item.parameter: item.source.value for item in call.latest_selection.params})
    dependency = None
    for parameter in call.params:
        value = parameter.source
        if isinstance(value, ConstantValueSource):
            constants[parameter.parameter] = physical_literal(value.value)
        elif isinstance(value, StepValueSource):
            sources[parameter.parameter] = value.path
        elif isinstance(value, CallValueSource):
            sources[parameter.parameter] = "target_id"
            dependency = PlanCandidateInputRef(plan_index=plan_offset + value.call_index)
        elif isinstance(value, EncoderValueSource) and all(
            isinstance(item, StepValueSource) for _, item in value.inputs
        ):
            sources[parameter.parameter] = {
                operand: item.path for operand, item in value.inputs
            }
        else:
            raise PlanningDeferredError("recipe cannot bind these encoder inputs")
    return {
        "parameter_sources": sources, "request_params": constants,
        "candidate_input_from_plan": dependency, "required": call.required,
    }


def _recipe_plans(
    step: Step, recipe: RecipeCapability, validation: CapabilityValidationResult,
    graph: CapabilityGraph, *, plan_offset: int,
) -> tuple[EndpointPlan, ...]:
    """Expand authored calls in order using existing physical plan dependencies."""
    endpoints = {
        endpoint.endpoint: endpoint
        for endpoint in graph.endpoints_for(recipe.broker, recipe.origin)
    }
    return tuple(
        _endpoint_plan(
            step, endpoints[call.endpoint], validation, graph,
            predicate_constraints=call.predicate_bindings,
            realize_search_predicate=index == 0,
        ).model_copy(
            update=_recipe_assignments(call, plan_offset=plan_offset, step=step)
        )
        for index, call in enumerate(recipe.calls)
    )


def _endpoint_plan(
    step: Step,
    endpoint: EndpointCapability,
    validation: CapabilityValidationResult,
    graph: CapabilityGraph,
    *,
    predicate_constraints: tuple[RequestConstraintCapability, ...] | None = None,
    realize_search_predicate: bool = True,
) -> EndpointPlan:
    realization = None
    if realize_search_predicate and isinstance(step, SearchStep) and step.predicate is not None:
        realization = realize_predicate(
            step.predicate,
            endpoint=endpoint,
            graph=graph,
            constraints=predicate_constraints,
        )
    request_params = {}
    if realize_search_predicate and isinstance(step, SearchStep) and step.selection is not None:
        binding = graph.latest_selection_for(endpoint.broker, endpoint.origin, endpoint.endpoint)
        if binding is None:
            raise PlanningDeferredError("latest has no declared discovery selection contract")
        request_params = {item.parameter: item.source.value for item in binding.params}
    return EndpointPlan(
        broker=endpoint.broker,
        origin=endpoint.origin,
        endpoint=endpoint.endpoint,
        semantic_type=validation.semantic_type,
        predicate_realization=realization,
        request_params=request_params,
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
        failures = "; ".join(
            f"{_source_text(item.source)}: {item.reason}"
            for item in validation.source_results if item.status == "deferred"
        )
        raise PlanningDeferredError(
            f"provider endpoint planning is deferred ({_context(validation)}): "
            f"{failures or validation.reason}"
        )
    if validation.status == "unsupported":
        raise _unsupported(validation)

    plans: list[EndpointPlan] = []
    for source_result in validation.source_results:
        endpoint = _select_one(validation, source_result)
        if source_result.recipes:
            recipe, = source_result.recipes
            plans.extend(_recipe_plans(
                step, recipe, validation, graph, plan_offset=len(plans),
            ))
        else:
            plans.append(_endpoint_plan(step, endpoint, validation, graph))
    return tuple(plans)


def _semantic_record_producer(record_type: str) -> str | None:
    _, at, qualifiers = record_type.partition("@")
    if not at:
        return None
    producer, _, _ = qualifiers.partition(":")
    return producer or None


def _get_record_requirement(step: GetStep) -> SemanticReference | None:
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


def _candidate_record_types(
    step: SearchStep | LookupStep, plan: EndpointPlan, graph: CapabilityGraph,
) -> tuple[str, ...]:
    """Use the selected required call's outputs for recipe-owned discovery."""
    if not plan.required:
        return ()
    if not graph.query_recipes(op=step.op, broker=plan.broker, origin=plan.origin):
        # Preserve compatibility only for operation/source pairs without recipes.
        return tuple(record.semantic_record_type for record in graph.records_for_endpoint(
            plan.broker, plan.origin, plan.endpoint,
        ))

    validation = validate_step_capabilities(step, graph)
    if validation.status != "supported":
        return ()
    plan_offset = 0
    record_types = []
    for result in validation.source_results:
        if result.recipes:
            if len(result.recipes) != 1:
                return ()
            recipe, = result.recipes
            if (recipe.broker, recipe.origin) == (plan.broker, plan.origin):
                for call in recipe.calls:
                    if call.endpoint != plan.endpoint or not call.required:
                        continue
                    assignments = _recipe_assignments(call, plan_offset=plan_offset, step=step)
                    if all(getattr(plan, key) == value for key, value in assignments.items()):
                        record_types.extend(output.semantic_record_type for output in call.outputs)
            plan_offset += len(recipe.calls)
        else:
            plan_offset += 1
    # An unmatched owned call must never borrow legacy endpoint-family evidence.
    return tuple(dict.fromkeys(record_types))


def _candidate_execution_guarantees(
    candidate_step: SearchStep | LookupStep,
    candidate_plan: EndpointPlan,
    consumer_step: GetStep,
    consumer_plan: EndpointPlan,
    graph: CapabilityGraph,
) -> bool:
    requirement = _get_record_requirement(consumer_step)
    if requirement is None:
        return False
    if isinstance(candidate_step, SearchStep) and candidate_step.selection is not None:
        # The full discovery execution contains candidates excluded by global
        # selection. Bind selected IDs until reuse can carry that semantic view.
        return False
    # Mapped fields do not establish what an authored projection requested.
    if candidate_plan.request_params != consumer_plan.request_params:
        return False
    if (
        candidate_plan.broker,
        candidate_plan.origin,
        candidate_plan.endpoint,
    ) != (
        consumer_plan.broker,
        consumer_plan.origin,
        consumer_plan.endpoint,
    ):
        return False

    matching = tuple(
        record_type
        for record_type in _candidate_record_types(candidate_step, candidate_plan, graph)
        if canonical_semantic_noun(record_type) == requirement.semantic_type
    )
    if not matching:
        return False

    if requirement.producer is None:
        return True

    for record_type in matching:
        producer = _semantic_record_producer(record_type)
        if producer == requirement.producer:
            return True
        if (
            producer is not None
            and _DYNAMIC_QUALIFIER.fullmatch(producer)
            and isinstance(candidate_step, SearchStep)
            and _predicate_requires_reference(candidate_step.predicate, requirement)
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
    candidate_step: SearchStep | LookupStep,
    consumer_plan: EndpointPlan,
    graph: CapabilityGraph,
) -> bool:
    endpoint = _capability_for_plan(graph, consumer_plan)
    if "target_id" not in endpoint.binding_roles:
        return False
    # Collection endpoints bind once. Singular endpoints are realized as one
    # physical call per surviving ID by the binder/runtime alignment layer.
    return True


def _mark_candidate_dependencies(
    workflow: WorkflowIR,
    planned_steps: tuple[StepRun, ...],
    graph: CapabilityGraph,
) -> tuple[StepRun, ...]:
    """Mark candidate and semantic-material lineage through one staged workflow."""

    rewritten = list(planned_steps)
    active_search_index: int | None = None
    current_candidate_index: int | None = None
    current_material_index: int | None = None

    for step_index, step in enumerate(workflow.steps):
        if isinstance(step, (SearchStep, LookupStep)):
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

        if isinstance(step, DeriveStep):
            if current_material_index is None:
                raise PlanningNotApplicableError(
                    f"derive step_index {step_index} requires an earlier materialized view"
                )
            rewritten[step_index] = rewritten[step_index].model_copy(
                update={
                    "material_input_from": MaterialInputRef(
                        step_index=current_material_index
                    )
                }
            )
            current_material_index = step_index
            continue

        if active_search_index is None:
            if rewritten[step_index].endpoint_plans:
                current_material_index = step_index
            continue

        search_step = workflow.steps[active_search_index]
        if not isinstance(search_step, (SearchStep, LookupStep)):
            active_search_index = None
            current_candidate_index = None
            current_material_index = (
                step_index if rewritten[step_index].endpoint_plans else None
            )
            continue

        if isinstance(step, ConfirmStep) and step.target is None:
            if current_candidate_index is None or current_material_index is None:
                raise PlanningNotApplicableError(
                    f"confirm step_index {step_index} requires an earlier materialized "
                    "candidate view"
                )
            current_run = rewritten[step_index]
            current_plans: list[EndpointPlan] = []
            for plan in current_run.endpoint_plans:
                if not _can_bind_candidate_ids(search_step, plan, graph):
                    endpoint = _capability_for_plan(graph, plan)
                    cardinality = (
                        "a singular target binding"
                        if "target_id" in endpoint.binding_roles
                        else "no target_id binding"
                    )
                    raise PlanningDeferredError(
                        "candidate confirmation requires runtime binding from the "
                        f"current candidate identities, but {endpoint.broker}/"
                        f"{endpoint.origin}/{endpoint.endpoint} has {cardinality}"
                    )
                current_plans.append(
                    plan.model_copy(
                        update={
                            "candidate_input_from": CandidateInputRef(
                                step_index=current_candidate_index
                            )
                        }
                    )
                )
            rewritten[step_index] = current_run.model_copy(
                update={
                    "endpoint_plans": tuple(current_plans),
                    "material_input_from": MaterialInputRef(
                        step_index=current_material_index
                    ),
                }
            )
            current_candidate_index = step_index
            current_material_index = step_index
            continue

        if not isinstance(step, GetStep) or getattr(step, "target", None) is not None:
            active_search_index = None
            current_candidate_index = None
            current_material_index = (
                step_index if rewritten[step_index].endpoint_plans else None
            )
            continue

        requirement = _get_record_requirement(step)
        recipe_target_input = any(
            path == ("target", "ids")
            for plan in rewritten[step_index].endpoint_plans
            for path in (plan.parameter_sources or {}).values()
        )
        if requirement is None and not recipe_target_input:
            active_search_index = None
            current_candidate_index = None
            current_material_index = (
                step_index if rewritten[step_index].endpoint_plans else None
            )
            continue

        if current_candidate_index is None or current_material_index is None:
            active_search_index = None
            current_candidate_index = None
            current_material_index = (
                step_index if rewritten[step_index].endpoint_plans else None
            )
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
                        if _candidate_execution_guarantees(
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
                    f"{endpoint.endpoint} has {cardinality}"
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
            update={
                "endpoint_plans": tuple(current_plans),
                "material_input_from": MaterialInputRef(
                    step_index=current_material_index
                ),
            }
        )
        current_material_index = step_index

    return tuple(rewritten)


def _same_forced_retrieval_input(
    owner_step: GetForcedPhotometryStep,
    owner_plan: EndpointPlan,
    lightcurve_step: GetLightcurveStep,
    supplement_plan: EndpointPlan,
) -> bool:
    if (
        owner_plan.request_params != supplement_plan.request_params
        or owner_plan.parameter_sources != supplement_plan.parameter_sources
        or owner_plan.predicate_realization != supplement_plan.predicate_realization
        or owner_plan.candidate_input_from_plan is not None
        or supplement_plan.candidate_input_from_plan is not None
    ):
        return False
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
) -> tuple[StepRun, ...]:
    rewritten = list(planned_steps)
    for step_index, step in enumerate(workflow.steps):
        if not isinstance(step, GetLightcurveStep):
            continue

        current_run = rewritten[step_index]
        current_plans = list(current_run.endpoint_plans)
        for plan_index, plan in enumerate(current_plans):
            if plan.execution_reuse_from is not None:
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


def _classification_material_plans(
    step: GetClassificationStep, workflow: WorkflowIR,
    earlier: list[StepRun], graph: CapabilityGraph,
) -> tuple[EndpointPlan, ...] | None:
    """Resolve a deferred dynamic selector from an actual earlier execution.

    This does not activate a search endpoint as a fresh retrieval recipe. The
    returned material plans must be marked as reuse by the same execution proof
    used for all other Gets below.
    """
    if step.target is not None or step.classifier is None or not step.sources:
        return None
    owner_index = None
    for index in range(len(earlier) - 1, -1, -1):
        previous = workflow.steps[index]
        if isinstance(previous, (SearchStep, LookupStep)):
            owner_index = index
            break
        if isinstance(previous, DeriveStep):
            continue
        if isinstance(previous, GetStep) and _get_record_requirement(previous) is not None:
            continue
        # A changed candidate population cannot reuse an unfiltered execution.
        return None
    if owner_index is None:
        return None
    owner = workflow.steps[owner_index]
    if not isinstance(owner, SearchStep):
        return None
    requirement = _get_record_requirement(step)
    if requirement is None or not _predicate_requires_reference(owner.predicate, requirement):
        return None
    plans = []
    for source in step.sources:
        if source.broker is None or source.origin is None:
            return None
        evidence = validate_step_capabilities(
            step.model_copy(update={"classifier": None, "sources": [source]}), graph,
        )
        if evidence.status != "supported" or not any(
            len(recipe.calls) == 1
            and all(
                isinstance(parameter.source, StepValueSource)
                and parameter.source.path in {("target", "ids"), ("classifier",)}
                for parameter in recipe.calls[0].params
            )
            for result in evidence.source_results for recipe in result.recipes
        ):
            return None
        matches = []
        for owner_plan in earlier[owner_index].endpoint_plans:
            if not owner_plan.required or owner_plan.candidate_input_from_plan is not None:
                continue
            if (owner_plan.broker, owner_plan.origin) != (source.broker, source.origin):
                continue
            if not any(
                canonical_semantic_noun(record_type) == "classification"
                and (producer := _semantic_record_producer(record_type)) is not None
                and _DYNAMIC_QUALIFIER.fullmatch(producer)
                for record_type in _candidate_record_types(owner, owner_plan, graph)
            ):
                continue
            material_plan = EndpointPlan(
                broker=owner_plan.broker, origin=owner_plan.origin,
                endpoint=owner_plan.endpoint,
            )
            if _candidate_execution_guarantees(owner, owner_plan, step, material_plan, graph):
                matches.append(material_plan)
        if len(matches) != 1:
            return None
        plans.extend(matches)
    return tuple(plans)


def _plan_workflow_step(
    step: Step, graph: CapabilityGraph, workflow: WorkflowIR, earlier: list[StepRun],
) -> tuple[EndpointPlan, ...]:
    """Plan one workflow occurrence, admitting orchestrated local steps."""

    if isinstance(step, (FilterStep, MatchStep)):
        return ()
    try:
        return plan_step(step, graph)
    except PlanningDeferredError:
        if isinstance(step, GetClassificationStep):
            material = _classification_material_plans(step, workflow, earlier, graph)
            if material is not None:
                return material
        raise


def plan_workflow(workflow: WorkflowIR, graph: CapabilityGraph) -> WorkflowRun:
    """Plan Steps, then mark candidate dependencies and proven execution reuse."""

    pending_run = WorkflowRun.from_workflow(workflow)
    earlier: list[StepRun] = []
    for step_run in pending_run.steps:
        earlier.append(StepRun(
            step_index=step_run.step_index,
            state=StepRunState.PLANNED,
            endpoint_plans=_plan_workflow_step(
                pending_run.step_at(step_run.step_index), graph, workflow, earlier,
            ),
        ))
    planned_steps = _mark_candidate_dependencies(workflow, tuple(earlier), graph)
    planned_steps = _mark_equivalent_forced_reuse(workflow, planned_steps)
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
