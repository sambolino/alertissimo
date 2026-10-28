"""Read-only discovery proof agrees with the planner's dynamic-classifier reuse."""

from dataclasses import replace

import pytest

from alertissimo.data_layer.runtime.capability_graph import build_capability_graph, canonical_semantic_noun
from alertissimo.data_layer.runtime.recipes import ConstantValueSource, RecipeParameter
from alertissimo.data_layer.representations import (
    InternalEdgeId, InternalExecutionId, InternalExecutionProvenance,
    InternalPortfolioId, InternalRecordId, InternalRecordSource, Portfolio,
    SemanticEdge, SemanticRecord,
)
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
from alertissimo.orchestration.normalization import StepPortfolioResult, apply_classification_selection
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


def test_discovery_material_is_reused_even_when_fresh_local_selection_is_supported(graph):
    owner, consumer = intent()
    assert validate_step_capabilities(consumer, graph).status == "supported"
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
        run = plan_workflow(WorkflowIR(steps=[owner, consumer]), graph)
        assert run.steps[1].endpoint_plans[0].endpoint == "query_probabilities"
        assert run.steps[1].endpoint_plans[0].execution_reuse_from is None
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


def test_local_classifier_selection_preserves_other_sources_edges_and_prior_snapshots():
    portfolios = []
    for broker, origin in (("alerce", "ztf"), ("alerce", "lsst"), ("fink", "ztf")):
        prefix = f"{broker}:{origin}"
        execution_id = InternalExecutionId(f"execution:{prefix}")
        source = InternalRecordSource(execution_id, "probabilities", "$[0]", 0)
        identifier = InternalPortfolioId(f"portfolio:{prefix}")
        # No summary here: these independent records exercise source scoping
        # without implying cross-survey candidate ownership.
        records = tuple(SemanticRecord(
            InternalRecordId(f"{prefix}:{model}"), f"classification@{model}:{broker}",
            {"provenance.producer.name": model}, source,
        ) for model in ("lc_classifier", "other_classifier"))
        edges = (
            SemanticEdge(InternalEdgeId(f"{prefix}:keep"), "--related_to--", identifier, InternalPortfolioId(f"portfolio:{prefix}:related")),
            SemanticEdge(InternalEdgeId(f"{prefix}:drop"), "--related_to--", records[0].internal_record_id, records[1].internal_record_id),
        )
        portfolios.append(Portfolio(
            identifier, records=records, edges=edges,
            executions=(InternalExecutionProvenance(execution_id, broker, origin, "probabilities"),),
        ))
    view = StepPortfolioResult(1, (), tuple(portfolios))
    step = GetClassificationStep(classifier="lc_classifier", sources=[Source(broker="alerce", origin="ztf")])
    selected = apply_classification_selection(step, view)
    actual, lsst, fink = selected.portfolios
    assert actual.records == portfolios[0].records[:1]
    assert actual.internal_portfolio_id != portfolios[0].internal_portfolio_id
    assert actual.executions == portfolios[0].executions
    assert len(actual.edges) == 1
    assert actual.edges[0].subject == actual.internal_portfolio_id
    assert actual.edges[0].target == portfolios[0].edges[0].target
    assert lsst is portfolios[1] and fink is portfolios[2]
    assert view.portfolios[0] is portfolios[0]
    assert len(view.portfolios[0].records) == len(view.portfolios[0].edges) == 2
