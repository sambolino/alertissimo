"""Structured predicate bindings with an isolated, non-activated provider fixture."""

from copy import deepcopy
import shutil

import pytest
import yaml

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor, TransportResult
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.runtime.capability_graph import CapabilityGraphError, build_capability_graph
from alertissimo.orchestration.binding import bind_endpoint
from alertissimo.orchestration.ir import (
    BooleanPredicate, ComparisonPredicate, NotPredicate, PredicateLiteral,
    SemanticReference, SemanticSearchStep, Source,
)
from alertissimo.orchestration.normalization import summary_object_identity
from alertissimo.orchestration.planner import PlanningDeferredError, plan_step, realize_predicate


def comparison(field="position.ra", operator=">=", value=120, **qualifiers):
    return ComparisonPredicate(
        left=SemanticReference(semantic_type="summary", field_path=field, **qualifiers),
        operator=operator, right=PredicateLiteral(value=value),
    )


def search(predicate):
    return SemanticSearchStep(sources=[Source(broker="antares", origin="ztf")],
                              semantic_type="summary", predicate=predicate)


@pytest.fixture
def provider(tmp_path):
    root = tmp_path / "providers"
    destination = root / "antares/ztf"
    shutil.copytree(PROVIDERS_ROOT / "antares/ztf", destination)
    path = destination / "capabilities.yaml"
    document = yaml.safe_load(path.read_text())
    # These coordinates exercise mechanics against existing untransformed
    # mappings. This fixture is not a production search-index field audit.
    document["predicate_bindings"] = {"search": [
        {"path": f"summary.position.{field}", "operator": op, "parameter": "query",
         "elasticsearch": {"field": field}}
        for field in ("ra", "dec") for op in ("=", "<", "<=", ">", ">=")
    ]}
    document["recipes"]["semantic_search"] = [{"calls": [{"endpoint": "search"}]}]
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    return root, destination


@pytest.mark.parametrize("operator,clause", [
    ("=", {"term": {"ra": 120}}),
    ("<", {"range": {"ra": {"lt": 120}}}),
    ("<=", {"range": {"ra": {"lte": 120}}}),
    (">", {"range": {"ra": {"gt": 120}}}),
    (">=", {"range": {"ra": {"gte": 120}}}),
])
def test_numeric_conditions_compile_plan_and_bind_as_one_query_key(provider, operator, clause):
    root, _ = provider
    graph = build_capability_graph(root)
    step = search(comparison(operator=operator))
    plan, = plan_step(step, graph)
    assert plan.predicate_realization.params == {"query": {"query": clause}}
    assert plan.predicate_realization.residual == step.predicate
    assert bind_endpoint(step, plan, EndpointRegistry(root)).params == {"query": {"query": clause}}
    recipe, = graph.query_recipes(broker="antares", origin="ztf", op="semantic_search")
    assert all(item.elasticsearch_field in {"ra", "dec"} for item in recipe.calls[0].predicate_bindings)


def test_conjunction_preserves_both_bounds_inversion_and_call_scope(provider):
    root, _ = provider
    graph = build_capability_graph(root)
    upper = ComparisonPredicate(left=PredicateLiteral(value=130), operator=">",
                                right=SemanticReference(semantic_type="summary", field_path="position.ra"))
    predicate = BooleanPredicate(operator="and", operands=(comparison(), upper))
    step = search(predicate)
    plan, = plan_step(step, graph)
    assert plan.predicate_realization.params == {"query": {"query": {"bool": {"filter": [
        {"range": {"ra": {"gte": 120}}}, {"range": {"ra": {"lt": 130}}},
    ]}}}}
    endpoint = next(e for e in graph.endpoints_for("antares", "ztf") if e.endpoint == "search")
    scoped = realize_predicate(predicate, endpoint=endpoint, graph=graph, constraints=())
    assert scoped.params == {} and scoped.residual == predicate


def test_nested_conjunction_keeps_distinct_fields_and_fixed_qualifiers(provider):
    root, _ = provider
    graph = build_capability_graph(root)
    left = comparison(producer="ztf", channel="antares")
    middle = comparison(field="position.dec", operator="<=", value=-5)
    right = comparison(operator="<", value=130)
    predicate = BooleanPredicate(operator="and", operands=(
        left, BooleanPredicate(operator="and", operands=(middle, right)),
    ))
    plan, = plan_step(search(predicate), graph)
    assert plan.predicate_realization.params == {"query": {"query": {"bool": {"filter": [
        {"range": {"ra": {"gte": 120}}},
        {"bool": {"filter": [{"range": {"dec": {"lte": -5}}}, {"range": {"ra": {"lt": 130}}}]}},
    ]}}}}
    assert plan.predicate_realization.residual == predicate


@pytest.mark.parametrize("predicate", [
    None, comparison(operator="!="), comparison(value=True), comparison(value="120"),
    comparison(value=float("inf")), comparison(value="120 OR match_all"),
    comparison(channel="fink"), comparison(producer="fink"), comparison(field="time.last_mjd"),
    NotPredicate(operand=comparison()),
    BooleanPredicate(operator="or", operands=(comparison(), comparison(value=130))),
    BooleanPredicate(operator="and", operands=(comparison(), comparison(value="130"))),
])
def test_unsupported_or_partial_query_cannot_supply_required_input(provider, predicate):
    root, _ = provider
    with pytest.raises(PlanningDeferredError, match="eligible predicate assignment"):
        plan_step(search(predicate), build_capability_graph(root))


@pytest.mark.parametrize("change,message", [
    ("field", "endpoint output mapping"), ("identifier", "field identifier"),
    ("operator", "numeric operator"), ("type", "dict filter"),
    ("exact", "dict filter"), ("values", "dict filter"),
    ("duplicate", "duplicate parameter"), ("unknown", "unknown keys"),
    ("transform", "untransformed"), ("mixed", "duplicate parameter"),
])
def test_unproven_structured_declarations_fail_loading(provider, change, message):
    root, destination = provider
    path = destination / "capabilities.yaml"
    document = yaml.safe_load(path.read_text())
    binding = document["predicate_bindings"]["search"][0]
    if change == "field":
        binding["elasticsearch"]["field"] = "properties.missing"
    elif change == "identifier":
        binding["elasticsearch"]["field"] = "ra;query"
    elif change == "operator":
        binding["operator"] = "!="
    elif change in {"exact", "values"}:
        binding[change] = False if change == "exact" else [120]
    elif change == "duplicate":
        document["predicate_bindings"]["search"].append(deepcopy(binding))
    elif change == "unknown":
        binding["elasticsearch"]["script"] = "invented"
    elif change == "mixed":
        document["predicate_bindings"]["search"].append({
            "path": "summary.position.dec", "operator": "!=", "parameter": "query",
        })
    elif change == "type":
        endpoint_path = destination / "endpoints.yaml"
        endpoints = yaml.safe_load(endpoint_path.read_text())
        endpoints["endpoints"]["search"]["params"]["query"]["type"] = "string"
        endpoint_path.write_text(yaml.safe_dump(endpoints, sort_keys=False))
    else:
        mappings_path = destination / "mappings.yaml"
        mappings = yaml.safe_load(mappings_path.read_text())
        mappings.setdefault("transforms", {})["summary@ztf:antares.position.ra"] = {
            "search_loci#ra": {"type": "jd_to_mjd"},
        }
        mappings_path.write_text(yaml.safe_dump(mappings, sort_keys=False))
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    with pytest.raises(CapabilityGraphError, match=message):
        build_capability_graph(root)


def test_public_facade_rechecks_structured_results_instead_of_trusting_the_query(provider):
    root, _ = provider
    graph = build_capability_graph(root)

    class Transport:
        calls = []

        def execute(self, spec, params, headers=None):
            assert spec.endpoint == "search"
            self.calls.append(deepcopy(params))
            # Simulate overbroad server output. The unchanged mappings must
            # still remove the row outside the scientific numeric predicate.
            return TransportResult(payload=[
                {"locus_id": "ANT-A", "ra": 125, "dec": -6,
                 "properties": {"ztf_object_id": "ZTF20aaaaaaa"}},
                {"locus_id": "ANT-B", "ra": 115, "dec": -6,
                 "properties": {"ztf_object_id": "ZTF20bbbbbbb"}},
            ], method="python")

    source = "objects from ztf via antares\nwhere summary.position.ra >= 120\n"
    assert validate_dsl(source, graph=graph, continue_from=None).is_runnable
    transport = Transport()
    result = execute_dsl(source, graph=graph, registry=EndpointRegistry(root), continue_from=None,
                         executor=RegistryEndpointExecutor(registry=EndpointRegistry(root),
                                                           transports={"python_client": transport}))
    assert transport.calls == [{"query": {"query": {"range": {"ra": {"gte": 120}}}}}]
    assert {summary_object_identity(p) for p in result.portfolios} == {("ztf", "ZTF20aaaaaaa")}


def test_ztf_activation_keeps_rubin_discovery_separate():
    graph = build_capability_graph()
    recipe, = graph.query_recipes(broker="antares", origin="ztf", op="semantic_search")
    assert all(item.elasticsearch_identity == "properties.ztf_object_id"
               for item in recipe.calls[0].predicate_bindings)
    assert graph.query_recipes(broker="antares", origin="lsst", op="semantic_search") == ()
