"""Confirmation recipes supply evidence; orchestration owns distinct-broker votes."""

from dataclasses import replace
import shutil

import pytest
import yaml

from alertissimo.data_layer.execution import EndpointRegistry
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.orchestration.binding import bind_endpoint_calls
from alertissimo.orchestration.ir import (
    ComparisonPredicate, ConfirmStep, PredicateLiteral, SemanticReference, Source,
    TargetSelector,
)
from alertissimo.orchestration.planner import PlanningAmbiguityError, PlanningDeferredError, plan_step
from alertissimo.orchestration.validation import validate_step_capabilities


def confirm(broker="alerce", origin="ztf", **kwargs):
    return ConfirmStep(sources=[Source(broker=broker, origin=origin)], **kwargs)


def classification(**qualifiers):
    return ComparisonPredicate(
        left=SemanticReference(semantic_type="classification", field_path="best.class", **qualifiers),
        operator="=", right=PredicateLiteral(value="SN"),
    )


@pytest.mark.parametrize("broker, origin, endpoint", [
    ("alerce", "ztf", "query_object"), ("alerce", "lsst", "query_object"),
    ("antares", "ztf", "get_by_ztf_object_id"), ("antares", "lsst", "get_by_lsst_dia_object_id"),
    ("fink", "ztf", "objects"), ("fink", "lsst", "objects"),
    ("lasair", "ztf", "objects"), ("lasair", "lsst", "object"),
])
def test_confirmation_uses_registry_tiers_without_legacy_tags(broker, origin, endpoint):
    graph = build_capability_graph()
    graph = replace(graph, endpoint_capabilities=tuple(
        replace(item, operation_types=()) for item in graph.endpoint_capabilities
    ))
    step = confirm(broker, origin)
    evidence = validate_step_capabilities(step, graph)
    assert evidence.status == "supported"
    recipe, = evidence.source_results[0].recipes
    assert recipe.op == "confirm"
    assert plan_step(step, graph)[0].endpoint == endpoint


def test_field_on_another_endpoint_cannot_establish_a_confirmation_vote():
    graph = build_capability_graph()
    # The family-wide classification record still includes best.class from
    # query_objects. Remove only the targeted query_object response's field.
    graph = replace(graph, field_mapping_capabilities=tuple(
        item for item in graph.field_mapping_capabilities
        if not (item.broker == "alerce" and item.origin == "ztf"
                and item.endpoint == "query_object" and item.relative_field_path == "best.class")
    ))
    assert any("best.class" in item.fields for item in graph.records_for_endpoint("alerce", "ztf", "query_object"))
    result = validate_step_capabilities(confirm(predicate=classification()), graph)
    assert result.status == "unsupported"
    assert result.candidates == ()


def test_confirmation_preserves_producer_and_channel_requirements():
    graph = build_capability_graph()
    assert validate_step_capabilities(confirm(predicate=classification(channel="alerce")), graph).status == "supported"
    assert validate_step_capabilities(confirm(predicate=classification(channel="lasair")), graph).status == "unsupported"
    assert validate_step_capabilities(confirm("lasair", predicate=classification(producer="missing")), graph).status == "unsupported"


def test_predicate_fields_without_object_identity_cannot_establish_a_vote():
    graph = build_capability_graph()
    graph = replace(graph, recipe_capabilities=tuple(
        recipe for recipe in graph.recipe_capabilities
        if recipe.op != "confirm" or recipe.broker != "alerce" or recipe.origin != "ztf"
        or recipe.calls[0].endpoint == "query_probabilities"
    ))
    predicate = ComparisonPredicate(
        left=SemanticReference(semantic_type="classification", field_path="provenance.producer.name"),
        operator="=", right=PredicateLiteral(value="lc_classifier"),
    )
    assert validate_step_capabilities(confirm(predicate=predicate), graph).status == "unsupported"


def test_confirmation_recipes_preserve_scalar_fanout_and_collection_binding():
    ids = ["ZTF20acpwljl", "ZTF20acpwljm"]
    graph, registry = build_capability_graph(), EndpointRegistry()
    for broker, parameter, expected in (
        ("alerce", "oid", ids), ("lasair", "objectIds", [",".join(ids)]),
    ):
        step = confirm(broker, target=TargetSelector(ids=ids, kind="object"))
        plan, = plan_step(step, graph)
        calls = bind_endpoint_calls(step, plan, registry)
        assert [call.params[parameter] for call in calls] == expected


def test_invalid_owned_confirmation_does_not_fall_back_to_lookup(tmp_path):
    root = tmp_path / "providers"
    destination = root / "alerce" / "ztf"
    shutil.copytree(PROVIDERS_ROOT / "alerce" / "ztf", destination)
    path = destination / "capabilities.yaml"
    doc = yaml.safe_load(path.read_text())
    doc["recipes"]["confirm"] = [{"calls": [{
        "endpoint": "query_object", "params": {"oid": {"value": "ZTF20acpwljl"}},
    }]}]
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    graph = build_capability_graph(root)
    result = validate_step_capabilities(confirm(), graph)
    assert result.status == "deferred"
    with pytest.raises(PlanningDeferredError, match="does not bind the candidate identities"):
        plan_step(confirm(), graph)


def test_duplicate_confirmation_recipes_remain_ambiguous():
    graph = build_capability_graph()
    recipe = next(item for item in graph.query_recipes(broker="alerce", origin="ztf", op="confirm")
                  if item.calls[0].endpoint == "query_object")
    graph = replace(graph, recipe_capabilities=graph.recipe_capabilities + (replace(recipe, alternative_index=99),))
    with pytest.raises(PlanningAmbiguityError, match=r"recipe\[99\]"):
        plan_step(confirm(), graph)


def test_nonobject_target_namespace_defers_before_binding():
    step = confirm(target=TargetSelector(ids=["1"], kind="alert"))
    graph = build_capability_graph()
    assert validate_step_capabilities(step, graph).status == "deferred"
    with pytest.raises(PlanningDeferredError, match="object target identities"):
        plan_step(step, graph)


@pytest.mark.parametrize("origin", ["ztf", "lsst"])
def test_unmigrated_confirmation_retains_compatibility_resolution(origin):
    graph = build_capability_graph()
    graph = replace(graph, recipe_capabilities=tuple(item for item in graph.recipe_capabilities if item.op != "confirm"))
    # Supply an explicit legacy lookup tier instead of borrowing a production
    # tag that is now redundant with the provider's lookup recipe.
    graph = replace(graph, endpoint_capabilities=tuple(
        replace(item, operation_types=("object_lookup",))
        if (item.broker, item.origin, item.endpoint) == ("alerce", origin, "query_object")
        else item for item in graph.endpoint_capabilities
    ))
    step = confirm(origin=origin)
    result = validate_step_capabilities(step, graph)
    assert result.status == "supported"
    assert result.source_results[0].recipes == ()
    assert plan_step(step, graph)[0].endpoint == "query_object"
