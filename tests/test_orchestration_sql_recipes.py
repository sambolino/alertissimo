"""A SQL operation tag cannot establish a binding for a whole IR query."""

from dataclasses import replace
import shutil

import pytest
import yaml

from alertissimo.data_layer.execution import EndpointRegistry
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.runtime.capability_graph import CapabilityGraphError, build_capability_graph
from alertissimo.orchestration.binding import bind_endpoint
from alertissimo.orchestration.ir import Source, SqlQueryStep
from alertissimo.orchestration.planner import PlanningAmbiguityError, PlanningDeferredError, plan_step
from alertissimo.orchestration.validation import validate_step_capabilities


def sql(origin="ztf", **kwargs):
    return SqlQueryStep(semantic_type="summary", query='SELECT objectId FROM objects WHERE name = "SN"',
                        sources=[Source(broker="lasair", origin=origin)], **kwargs)


def edit_yaml(path, update):
    doc = yaml.safe_load(path.read_text())
    update(doc)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def direct_query_provider(tmp_path):
    """A local representative whole-query contract; no real API is invoked."""
    root = tmp_path / "providers"
    destination = root / "lasair" / "ztf"
    shutil.copytree(PROVIDERS_ROOT / "lasair" / "ztf", destination)
    def endpoints(doc):
        endpoint = doc["endpoints"]["query"]
        endpoint["params"] = {"statement": {"type": "string", "required": True, "bind": "query"}}
        endpoint["server_filters"] = ["statement"]
        endpoint["projection"] = {"supports_columns": False}
        endpoint["operation_types"] = []
    edit_yaml(destination / "endpoints.yaml", endpoints)
    (destination / "capabilities.yaml").write_text(yaml.safe_dump({
        "broker": "lasair", "origin": "ztf", "recipes": {"sql_query": [{"calls": [{
            "endpoint": "query", "params": {"statement": {"from": "step.query"}},
        }]}]},
    }), encoding="utf-8")
    return root, destination


@pytest.mark.parametrize("origin", ["ztf", "lsst"])
def test_lasair_split_sql_contract_defers_before_planning(origin):
    graph = build_capability_graph()
    assert graph.query_endpoints(broker="lasair", origin=origin, operation_type="sql_query")
    result = validate_step_capabilities(sql(origin), graph)
    assert result.status == "deferred"
    assert result.candidates == ()
    with pytest.raises(PlanningDeferredError, match="whole-query binding"):
        plan_step(sql(origin), graph)


def test_declared_whole_query_binds_to_the_authored_physical_parameter(tmp_path):
    root, _ = direct_query_provider(tmp_path)
    step, graph = sql(), build_capability_graph(root)
    result = validate_step_capabilities(step, graph)
    assert result.status == "supported"
    assert result.source_results[0].recipes[0].op == "sql_query"
    plan, = plan_step(step, graph)
    assert plan.parameter_sources == {"statement": ("query",)}
    assert bind_endpoint(step, plan, EndpointRegistry(root)).params == {"statement": step.query}


def test_query_source_requires_the_physical_query_role(tmp_path):
    root, destination = direct_query_provider(tmp_path)
    edit_yaml(destination / "endpoints.yaml", lambda doc: doc["endpoints"]["query"]["params"]["statement"].pop("bind"))
    with pytest.raises(CapabilityGraphError, match="whole queries require a query encoder role"):
        build_capability_graph(root)


def test_constant_query_cannot_replace_the_requested_ir_query(tmp_path):
    root, destination = direct_query_provider(tmp_path)
    def capabilities(doc):
        doc["recipes"]["sql_query"][0]["calls"][0]["params"]["statement"] = {"value": "SELECT 1"}
    edit_yaml(destination / "capabilities.yaml", capabilities)
    with pytest.raises(PlanningDeferredError, match="declared whole-query binding"):
        plan_step(sql(), build_capability_graph(root))


def test_criteria_cannot_be_silently_dropped_from_a_sql_recipe(tmp_path):
    root, _ = direct_query_provider(tmp_path)
    with pytest.raises(PlanningDeferredError, match="inputs have no declared translation"):
        plan_step(sql(criteria={"limit": 1}), build_capability_graph(root))


def test_competing_sql_recipes_remain_ambiguous(tmp_path):
    root, _ = direct_query_provider(tmp_path)
    graph = build_capability_graph(root)
    recipe, = graph.query_recipes(op="sql_query")
    graph = replace(graph, recipe_capabilities=graph.recipe_capabilities + (replace(recipe, alternative_index=1),))
    with pytest.raises(PlanningAmbiguityError, match=r"recipe\[1\]"):
        plan_step(sql(), graph)
