"""Semantic discovery uses authored recipes and shares cone feasibility rules."""

from dataclasses import replace
import shutil

import pytest
import yaml

from alertissimo.data_layer.execution import EndpointRegistry
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.orchestration.binding import bind_endpoint
from alertissimo.orchestration.ir import (
    ComparisonPredicate, PredicateLiteral, SemanticReference, SemanticSearchStep,
    Source, TimeContext,
)
from alertissimo.orchestration.planner import (
    PlanningAmbiguityError, PlanningDeferredError, UnsupportedStepError, plan_step,
)
from alertissimo.orchestration.validation import (
    candidate_capabilities, validate_step_capabilities,
)


def search(origin="lsst", **kwargs):
    return SemanticSearchStep(
        semantic_type="summary", sources=[Source(broker="alerce", origin=origin)], **kwargs,
    )


def local_provider(tmp_path):
    root = tmp_path / "providers"
    destination = root / "alerce" / "lsst"
    shutil.copytree(PROVIDERS_ROOT / "alerce" / "lsst", destination)
    return root, destination


def edit_yaml(path, update):
    doc = yaml.safe_load(path.read_text())
    update(doc)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


@pytest.mark.parametrize("origin", ["ztf", "lsst"])
def test_semantic_recipe_survives_removal_of_legacy_operation_tags(origin):
    graph = build_capability_graph()
    graph = replace(graph, endpoint_capabilities=tuple(
        replace(item, operation_types=()) if item.broker == "alerce" else item
        for item in graph.endpoint_capabilities
    ))
    step = search(origin)
    evidence = validate_step_capabilities(step, graph)
    assert evidence.status == "supported"
    recipe, = evidence.source_results[0].recipes
    assert recipe.op == "semantic_search"
    plan, = plan_step(step, graph)
    assert plan.endpoint == "query_objects"
    assert bind_endpoint(step, plan, EndpointRegistry()).params == {}


@pytest.mark.parametrize("kwargs", [
    {"criteria": {"limit": 1}},
    {"time_context": TimeContext(start_time="2026-01-01T00:00:00", end_time="2026-01-02T00:00:00")},
])
def test_untranslated_discovery_inputs_defer_before_binding(kwargs):
    graph = build_capability_graph()
    step = search(**kwargs)
    evidence = validate_step_capabilities(step, graph)
    assert evidence.status == "deferred"
    assert not candidate_capabilities(step, graph)
    with pytest.raises(PlanningDeferredError, match="inputs have no declared translation"):
        plan_step(step, graph)


@pytest.mark.parametrize("operator, expected", [(">=", {"classifier": "lc_classifier", "probability": 0.8}), ("<", {})])
def test_semantic_recipe_keeps_explicit_predicate_operators(operator, expected):
    predicate = ComparisonPredicate(
        left=SemanticReference(
            semantic_type="classification", field_path="best.probability", producer="lc_classifier",
        ),
        operator=operator, right=PredicateLiteral(value=0.8),
    )
    step = search(predicate=predicate)
    plan, = plan_step(step, build_capability_graph())
    assert plan.predicate_realization.params == expected
    assert plan.predicate_realization.residual == (None if expected else predicate)
    assert bind_endpoint(step, plan, EndpointRegistry()).params == expected


def test_incompatible_owned_recipe_cannot_fall_back_to_query_objects(tmp_path):
    root, destination = local_provider(tmp_path)
    def capabilities(doc):
        doc["recipes"]["semantic_search"] = [{"calls": [{
            "endpoint": "query_lightcurve", "params": {"oid": {"value": 1}},
        }]}]
    edit_yaml(destination / "capabilities.yaml", capabilities)
    graph = build_capability_graph(root)
    assert graph.query_endpoints(broker="alerce", origin="lsst", operation_type="object_search")
    assert validate_step_capabilities(search(), graph).status == "unsupported"
    with pytest.raises(UnsupportedStepError, match="no semantic search recipe"):
        plan_step(search(), graph)


def test_optional_output_cannot_establish_the_discovery_population(tmp_path):
    root, destination = local_provider(tmp_path)
    def capabilities(doc):
        doc["recipes"]["semantic_search"] = [{"calls": [
            {"endpoint": "query_objects", "required": False},
            {"endpoint": "query_objects"},
        ]}]
    edit_yaml(destination / "capabilities.yaml", capabilities)
    graph = build_capability_graph(root)
    assert validate_step_capabilities(search(), graph).status == "deferred"
    with pytest.raises(PlanningDeferredError, match="discovery call must be required"):
        plan_step(search(), graph)


def test_duplicate_discovery_recipes_remain_ambiguous():
    graph = build_capability_graph()
    recipe, = graph.query_recipes(broker="alerce", origin="lsst", op="semantic_search")
    graph = replace(graph, recipe_capabilities=graph.recipe_capabilities + (
        replace(recipe, alternative_index=1),
    ))
    assert len(validate_step_capabilities(search(), graph).source_results[0].recipes) == 2
    with pytest.raises(PlanningAmbiguityError, match=r"recipe\[1\]"):
        plan_step(search(), graph)


@pytest.mark.parametrize("origin", ["ztf", "lsst"])
def test_unmigrated_provider_retains_the_legacy_compatibility_path(origin):
    graph = build_capability_graph()
    graph = replace(graph, recipe_capabilities=tuple(
        recipe for recipe in graph.recipe_capabilities if recipe.op != "semantic_search"
    ))
    # Compatibility tags belong to this legacy fixture, independently of
    # which production provider declarations have migrated to recipes.
    graph = replace(graph, endpoint_capabilities=tuple(
        replace(item, operation_types=("object_search",))
        if (item.broker, item.origin, item.endpoint) == ("alerce", origin, "query_objects")
        else item for item in graph.endpoint_capabilities
    ))
    step = search(origin)
    evidence = validate_step_capabilities(step, graph)
    assert evidence.status == "supported"
    assert evidence.source_results[0].recipes == ()
    assert plan_step(step, graph)[0].endpoint == "query_objects"
