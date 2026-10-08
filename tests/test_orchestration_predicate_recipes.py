"""Predicate translations retain their endpoint and discovery-call boundaries."""

import shutil

import pytest
import yaml

from alertissimo.data_layer.execution import EndpointRegistry
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraphError, build_capability_graph,
)
from alertissimo.orchestration.binding import bind_endpoint_calls
from alertissimo.orchestration.ir import (
    BooleanPredicate, ComparisonPredicate, ConeSearchStep, NotPredicate,
    PredicateLiteral, SemanticReference, Source,
)
from alertissimo.orchestration.planner import plan_step, realize_predicate


def local_provider(tmp_path, broker="alerce", origin="lsst"):
    root = tmp_path / "providers"
    destination = root / broker / origin
    shutil.copytree(PROVIDERS_ROOT / broker / origin, destination)
    return root, destination


def edit_yaml(path, update):
    document = yaml.safe_load(path.read_text())
    update(document)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def comparison(field="best.probability", operator=">=", value=0.8, **qualifiers):
    return ComparisonPredicate(
        left=SemanticReference(semantic_type="classification", field_path=field, **qualifiers),
        operator=operator, right=PredicateLiteral(value=value),
    )


def endpoint_and_graph(root=None):
    graph = build_capability_graph(root)
    endpoint = next(item for item in graph.endpoints_for("alerce", "lsst") if item.endpoint == "query_objects")
    return endpoint, graph


def test_translations_compile_once_and_discovery_call_owns_them():
    endpoint, graph = endpoint_and_graph()
    constraints = graph.request_constraints_for(endpoint.broker, endpoint.origin, endpoint.endpoint)
    assert {(item.parameter, item.semantic_path, item.operator) for item in constraints} == {
        ("classifier", "classification.provenance.producer.name", "="),
        ("class_name", "classification.best.class", "="),
        ("probability", "classification.best.probability", ">="),
    }
    recipe, = graph.query_recipes(broker="alerce", origin="lsst", op="cone_search")
    assert set(recipe.calls[0].predicate_bindings) == set(constraints)
    assert all(
        not call.predicate_bindings
        for recipe in graph.query_recipes(broker="alerce", origin="lsst")
        if recipe.op != "cone_search"
        for call in recipe.calls
    )


@pytest.mark.parametrize("change, message", [
    ("missing_operator", "missing keys"),
    ("operator", "IR comparison operator"),
    ("parameter", "declared parameter"),
    ("non_filter", "server filter"),
    ("path", "endpoint ontology mapping"),
    ("other_endpoint_path", "endpoint ontology mapping"),
    ("endpoint", "unknown endpoint"),
    ("duplicate", "duplicate parameter"),
    ("unknown_key", "unknown keys"),
])
def test_invalid_bindings_fail_without_legacy_fallback(tmp_path, change, message):
    root, destination = local_provider(tmp_path)
    def invalid(doc):
        bindings = doc["predicate_bindings"]["query_objects"]
        binding = bindings[-1]
        if change == "missing_operator":
            binding.pop("operator")
        elif change == "operator":
            binding["operator"] = "approximately"
        elif change == "parameter":
            binding["parameter"] = "missing"
        elif change == "non_filter":
            binding["parameter"] = "format"
        elif change == "path":
            binding["path"] = "classification.best.missing"
        elif change == "other_endpoint_path":
            binding["path"] = "classification.assessment.{output}.probability"
        elif change == "endpoint":
            doc["predicate_bindings"]["missing"] = doc["predicate_bindings"].pop("query_objects")
        elif change == "duplicate":
            bindings.append(binding.copy())
        else:
            binding["adapter"] = "invented"
    edit_yaml(destination / "capabilities.yaml", invalid)
    with pytest.raises(CapabilityGraphError, match=message):
        build_capability_graph(root)


def test_predicate_parameter_cannot_also_have_a_recipe_constant(tmp_path):
    root, destination = local_provider(tmp_path)
    def conflict(doc):
        doc["recipes"]["cone_search"][0]["calls"][0]["params"]["probability"] = {"value": 0.9}
    edit_yaml(destination / "capabilities.yaml", conflict)
    with pytest.raises(CapabilityGraphError, match="predicate binding conflicts"):
        build_capability_graph(root)


def test_unmigrated_legacy_provider_keeps_existing_translations(tmp_path):
    root, destination = local_provider(tmp_path)
    document = yaml.safe_load((destination / "capabilities.yaml").read_text())
    bindings = document.pop("predicate_bindings")
    legacy = {
        "broker": "alerce", "origin": "lsst", "constraints": {
            endpoint: {
                item["parameter"]: {"semantic_path": item["path"], "operator": item["operator"]}
                for item in items
            } for endpoint, items in bindings.items()
        },
    }
    (destination / "request_mappings.yaml").write_text(yaml.safe_dump(legacy), encoding="utf-8")
    with pytest.raises(CapabilityGraphError, match="must not also be authored"):
        build_capability_graph(root)
    (destination / "capabilities.yaml").write_text(yaml.safe_dump(document), encoding="utf-8")
    endpoint, graph = endpoint_and_graph(root)
    result = realize_predicate(comparison(producer="lc_classifier"), endpoint=endpoint, graph=graph)
    assert result.residual is None
    assert result.params == {"classifier": "lc_classifier", "probability": 0.8}
    recipe, = graph.query_recipes(op="cone_search")
    assert len(recipe.calls[0].predicate_bindings) == 3


def test_comparison_inversion_and_explicit_call_scope():
    endpoint, graph = endpoint_and_graph()
    predicate = comparison(producer="lc_classifier")
    reversed_predicate = ComparisonPredicate(left=predicate.right, operator="<=", right=predicate.left)
    assert realize_predicate(reversed_predicate, endpoint=endpoint, graph=graph).params == {
        "classifier": "lc_classifier", "probability": 0.8,
    }
    result = realize_predicate(predicate, endpoint=endpoint, graph=graph, constraints=())
    assert result.pushdown is None
    assert result.residual == predicate
    assert result.params == {}


@pytest.mark.parametrize("kind", ["not", "or", "conflict", "channel", "direction"])
def test_relocation_preserves_predicates_that_must_remain_residual(kind):
    endpoint, graph = endpoint_and_graph()
    predicate = comparison(producer="lc_classifier")
    if kind == "not":
        predicate = NotPredicate(operand=predicate)
    elif kind == "or":
        predicate = BooleanPredicate(operator="or", operands=(predicate, comparison(value=0.9)))
    elif kind == "conflict":
        predicate = BooleanPredicate(operator="and", operands=(predicate, comparison(value=0.9, producer="lc_classifier")))
    elif kind == "channel":
        predicate = comparison(producer="lc_classifier", channel="fink")
    else:
        predicate = comparison(operator="<", producer="lc_classifier")
    result = realize_predicate(predicate, endpoint=endpoint, graph=graph)
    assert result.pushdown is None
    assert result.residual == predicate
    assert result.params == {}


@pytest.mark.parametrize("discovery_binding", [False, True])
@pytest.mark.parametrize("required", [False, True])
def test_enrichment_bindings_do_not_consume_the_discovery_predicate(tmp_path, discovery_binding, required):
    root, destination = local_provider(tmp_path, "lasair", "ztf")
    binding = {"path": "summary.identity.object_id", "operator": "=", "parameter": "object_filter"}
    def endpoints(doc):
        for name in ("cone", "query"):
            spec = doc["endpoints"][name]
            spec["params"]["object_filter"] = {"type": "string"}
            spec.setdefault("server_filters", []).append("object_filter")
    def capabilities(doc):
        doc["predicate_bindings"] = {"query": [binding]}
        if discovery_binding:
            doc["predicate_bindings"]["cone"] = [binding]
        doc["recipes"]["cone_search"][0]["calls"][1]["required"] = required
    edit_yaml(destination / "endpoints.yaml", endpoints)
    edit_yaml(destination / "capabilities.yaml", capabilities)
    predicate = ComparisonPredicate(
        left=SemanticReference(semantic_type="summary", field_path="identity.object_id"),
        operator="=", right=PredicateLiteral(value="ZTF20acpwljl"),
    )
    step = ConeSearchStep(
        semantic_type="summary", ra=120, dec=-6, radius=30,
        sources=[Source(broker="lasair", origin="ztf")], predicate=predicate,
    )
    graph = build_capability_graph(root)
    discovery, enrichment = plan_step(step, graph)
    assert enrichment.predicate_realization is None
    assert enrichment.required is required
    assert enrichment.candidate_input_from_plan.plan_index == 0
    realization = discovery.predicate_realization
    assert realization.params == ({"object_filter": "ZTF20acpwljl"} if discovery_binding else {})
    assert realization.residual == (None if discovery_binding else predicate)
    bound, = bind_endpoint_calls(
        step, enrichment, EndpointRegistry(root), runtime_values={"target_id": ("ZTF20acpwljl",)},
    )
    assert "object_filter" not in bound.params
    assert bound.params["conditions"] == 'objects.objectId IN ("ZTF20acpwljl")'
