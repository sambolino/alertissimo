"""Discovery aliases and mandatory physical inputs cannot invent IR translations."""

from datetime import timedelta

import pytest
import yaml

from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor, TransportResult
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.orchestration.binding import bind_endpoint
from alertissimo.orchestration.ir import SemanticSearchStep, Source, TimeContext
from alertissimo.orchestration.planner import PlanningDeferredError, UnsupportedStepError, plan_step
from alertissimo.orchestration.validation import candidate_capabilities, validate_step_capabilities


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def search(broker="example", origin="survey", **kwargs):
    return SemanticSearchStep(semantic_type="summary", sources=[Source(broker=broker, origin=origin)], **kwargs)


@pytest.mark.parametrize("broker", ["antares", "fink"])
@pytest.mark.parametrize("origin", ["ztf", "lsst"])
def test_untranslated_real_discovery_defers_before_binding(graph, broker, origin):
    step = search(broker, origin)
    evidence = validate_step_capabilities(step, graph)
    assert evidence.status == "deferred"
    assert "recipe translation" in evidence.source_results[0].reason
    assert not candidate_capabilities(step, graph)
    with pytest.raises(PlanningDeferredError, match="recipe translation"):
        plan_step(step, graph)


@pytest.mark.parametrize("origin", ["ztf", "lsst"])
def test_lasair_without_a_generic_discovery_contract_remains_unsupported(graph, origin):
    step = search("lasair", origin)
    assert validate_step_capabilities(step, graph).status == "unsupported"
    with pytest.raises(UnsupportedStepError):
        plan_step(step, graph)


def test_wildcard_discovery_cannot_reintroduce_ineligible_legacy_aliases(graph):
    step = SemanticSearchStep(semantic_type="summary", sources=[Source(origin="lsst")])
    evidence = validate_step_capabilities(step, graph)
    assert evidence.status == "supported"
    assert {(item.broker, item.endpoint) for item in evidence.candidates} == {("alerce", "query_objects")}
    plan, = plan_step(step, graph)
    assert (plan.broker, plan.origin, plan.endpoint) == ("alerce", "lsst", "query_objects")


def test_declared_source_is_not_dropped_when_another_source_is_feasible(graph):
    step = SemanticSearchStep(semantic_type="summary", sources=[
        Source(broker="alerce", origin="lsst"), Source(broker="antares", origin="lsst"),
    ])
    evidence = validate_step_capabilities(step, graph)
    assert evidence.status == "deferred"
    assert [result.status for result in evidence.source_results] == ["supported", "deferred"]
    with pytest.raises(PlanningDeferredError, match="physical inputs.*query"):
        plan_step(step, graph)


def local_contract(tmp_path, *, params=None, operations=("object_search",), fixed=None, transport=None, recipe=None):
    root = tmp_path / "providers"
    destination = root / "example" / "survey"
    destination.mkdir(parents=True)
    identity = {"broker": "example", "origin": "survey"}
    documents = {
        "endpoints.yaml": {
            **identity, "base_url": "https://example.invalid",
            "transport_defaults": {"fixed_params": fixed or {}},
            "endpoints": {"discover": {
                "path": "/discover", "method": "POST", "operation_types": list(operations),
                "params": params or {}, "transport": transport or {}, "output": {"type": "array"},
            }},
        },
        "mappings.yaml": {
            **identity, "payloads": {"discover": {"path": "[]"}},
            "mappings": {"summary@survey:example.identity.object_id": ["discover#oid"]},
        },
        "unmapped_fields.yaml": {},
    }
    if recipe is not None:
        documents["capabilities.yaml"] = {
            **identity, "recipes": {"semantic_search": [{"calls": [{"endpoint": "discover", "params": recipe}]}]},
        }
    for filename, doc in documents.items():
        (destination / filename).write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return root, build_capability_graph(root)


def test_parameter_free_specialized_population_needs_an_authored_recipe(tmp_path):
    _, graph = local_contract(tmp_path, operations=("anomaly_search", "alert_search"))
    assert validate_step_capabilities(search(), graph).status == "deferred"
    with pytest.raises(PlanningDeferredError, match="specialized search populations"):
        plan_step(search(), graph)


def test_mandatory_query_input_is_not_inferred_from_a_generic_operation_tag(tmp_path):
    _, graph = local_contract(tmp_path, params={"query": {"type": "dict", "required": True}})
    endpoint, = graph.endpoint_capabilities
    assert endpoint.required_params == ("query",)
    with pytest.raises(PlanningDeferredError, match="physical inputs.*query"):
        plan_step(search(), graph)


def test_authored_recipe_can_supply_the_mandatory_physical_input(tmp_path):
    query = {"query": {"match_all": {}}}
    root, graph = local_contract(
        tmp_path, params={"query": {"type": "dict", "required": True}},
        recipe={"query": {"value": query}},
    )
    assert graph.endpoint_capabilities[0].required_params == ("query",)
    assert validate_step_capabilities(search(), graph).status == "supported"
    plan, = plan_step(search(), graph)
    assert bind_endpoint(search(), plan, EndpointRegistry(root)).params == {"query": query}


def test_physical_defaults_are_not_missing_caller_inputs(tmp_path):
    root, graph = local_contract(
        tmp_path,
        params={
            "query": {"type": "dict", "required": True},
            "limit": {"type": "integer", "required": True, "default": 0},
            "count": {"type": "boolean", "required": True, "default": False},
            "format": {"type": "string", "required": True},
        },
        fixed={"query": {"scope": "declared"}, "format": "csv"},
        transport={"fixed_params": {"format": "json"}},
    )
    assert graph.endpoint_capabilities[0].required_params == ()
    plan, = plan_step(search(), graph)
    registry = EndpointRegistry(root)
    bound = bind_endpoint(search(), plan, registry)

    class CaptureTransport:
        def execute(self, spec, params):
            self.params = dict(params)
            return TransportResult(payload=[])

    transport = CaptureTransport()
    result = RegistryEndpointExecutor(registry, transports={"rest": transport}).execute(
        plan.broker, plan.origin, plan.endpoint, params=bound.params,
    )
    assert transport.params == {
        "query": {"scope": "declared"}, "limit": 0, "count": False, "format": "json",
    }
    assert result.execution_provenance.params == transport.params


@pytest.mark.parametrize("kwargs", [
    {"criteria": {"query": {"match_all": {}}}},
    {"time_context": TimeContext(window=timedelta(days=1))},
])
def test_legacy_discovery_does_not_discard_untranslated_ir_inputs(tmp_path, kwargs):
    _, graph = local_contract(tmp_path)
    with pytest.raises(PlanningDeferredError, match="criteria/time_context"):
        plan_step(search(**kwargs), graph)
