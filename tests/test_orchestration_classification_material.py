"""Read-only discovery proof agrees with the planner's dynamic-classifier reuse."""

from dataclasses import replace

import pytest

from alertissimo.data_layer.runtime.capability_graph import build_capability_graph, canonical_semantic_noun
from alertissimo.data_layer.runtime.recipes import ConstantValueSource, RecipeParameter
from alertissimo.orchestration.ir import (
    FilterStep, GetClassificationStep, GetLightcurveStep, LookupStep,
    SearchSelection, SemanticSearchStep, Source, TargetSelector, WorkflowIR,
)
from alertissimo.orchestration.ir.predicates import (
    BooleanPredicate, ComparisonPredicate, NotPredicate, PredicateLiteral,
    SemanticReference, predicate_requires_reference,
)
from alertissimo.orchestration.planner import PlanningAmbiguityError, PlanningDeferredError, plan_workflow
from alertissimo.orchestration.runtime import EndpointPlanRef
from alertissimo.orchestration.validation import (
    classification_material_capabilities, validate_step_capabilities,
)


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def intent():
    sources = [Source(broker="alerce", origin="lsst")]
    predicate = ComparisonPredicate(
        left=SemanticReference(semantic_type="classification", producer="lc_classifier", field_path="best.class"),
        operator="=", right=PredicateLiteral(value="SN"),
    )
    owner = SemanticSearchStep(semantic_type="summary", sources=sources, predicate=predicate)
    consumer = GetClassificationStep(classifier="lc_classifier", sources=sources)
    return owner, consumer


def test_discovery_material_proves_reuse_without_activating_fresh_selector(graph):
    owner, consumer = intent()
    assert validate_step_capabilities(consumer, graph).status == "deferred"
    material, = classification_material_capabilities(consumer, (owner,), graph)
    assert material.owner_index == 0
    assert material.source == consumer.sources[0]
    assert material.endpoint.endpoint == "query_objects"
    assert material.record_types == ("classification@{producer}:alerce",)
    run = plan_workflow(WorkflowIR(steps=[owner, consumer]), graph)
    assert run.steps[1].endpoint_plans[0].execution_reuse_from == EndpointPlanRef(step_index=0, plan_index=0)


def test_intervening_retrieval_preserves_the_discovery_owner_index(graph):
    owner, consumer = intent()
    retrieval = GetLightcurveStep(sources=consumer.sources)
    material, = classification_material_capabilities(consumer, (owner, retrieval), graph)
    assert material.owner_index == 0
    run = plan_workflow(WorkflowIR(steps=[owner, retrieval, consumer]), graph)
    assert run.steps[2].endpoint_plans[0].execution_reuse_from == EndpointPlanRef(step_index=0, plan_index=0)


@pytest.mark.parametrize("barrier", ["filter", "selection", "lookup", "target", "source", "or", "not"])
def test_unproven_context_does_not_supply_material(graph, barrier):
    owner, consumer = intent()
    earlier = (owner,)
    if barrier == "filter":
        earlier += (FilterStep(predicate=owner.predicate),)
    elif barrier == "selection":
        earlier = (owner.model_copy(update={"selection": SearchSelection(latest=1)}),)
    elif barrier == "lookup":
        earlier = (LookupStep(target=TargetSelector(ids=["1"], kind="object"), sources=consumer.sources),)
    elif barrier == "target":
        consumer = consumer.model_copy(update={"target": TargetSelector(ids=["1"], kind="object")})
    elif barrier == "source":
        consumer = consumer.model_copy(update={"sources": [Source(origin="lsst")]})
    elif barrier == "or":
        earlier = (owner.model_copy(update={"predicate": BooleanPredicate(
            operator="or", operands=(owner.predicate, owner.predicate),
        )}),)
    else:
        earlier = (owner.model_copy(update={"predicate": NotPredicate(operand=owner.predicate)}),)
    assert classification_material_capabilities(consumer, earlier, graph) == ()


@pytest.mark.parametrize("change", ["outputs", "constants", "ambiguous"])
def test_owned_call_contract_limits_read_only_and_planner_proof(graph, change):
    owner, consumer = intent()
    recipes = []
    for recipe in graph.recipe_capabilities:
        if (recipe.broker, recipe.origin, recipe.op) != ("alerce", "lsst", "semantic_search"):
            recipes.append(recipe)
            continue
        call, = recipe.calls
        if change == "outputs":
            call = replace(call, outputs=tuple(
                output for output in call.outputs
                if canonical_semantic_noun(output.semantic_record_type) != "classification"
            ))
        elif change == "constants":
            call = replace(call, params=call.params + (RecipeParameter("page_size", ConstantValueSource(100)),))
        recipes.append(replace(recipe, calls=(call,)))
        if change == "ambiguous":
            recipes.append(replace(recipe, alternative_index=1))
    graph = replace(graph, recipe_capabilities=tuple(recipes))
    assert classification_material_capabilities(consumer, (owner,), graph) == ()
    if change != "ambiguous":
        with pytest.raises(PlanningDeferredError):
            plan_workflow(WorkflowIR(steps=[owner, consumer]), graph)
    else:
        with pytest.raises(PlanningAmbiguityError):
            plan_workflow(WorkflowIR(steps=[owner, consumer]), graph)


def test_positive_reference_proof_preserves_qualifiers_and_conjunctions():
    owner, consumer = intent()
    requirement = SemanticReference(semantic_type="classification", producer=consumer.classifier)
    assert predicate_requires_reference(owner.predicate, requirement)
    assert predicate_requires_reference(BooleanPredicate(
        operator="and", operands=(owner.predicate, owner.predicate),
    ), requirement)
    assert not predicate_requires_reference(owner.predicate, requirement.model_copy(update={"producer": "other"}))
    assert not predicate_requires_reference(owner.predicate, requirement.model_copy(update={"channel": "other"}))
