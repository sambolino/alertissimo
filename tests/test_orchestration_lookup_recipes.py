"""Lookup recipes preserve identity namespaces, cardinality, and ambiguity."""

import shutil

import pytest
import yaml

from alertissimo.data_layer.execution import EndpointRegistry
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.runtime.capability_graph import CapabilityGraphError, build_capability_graph
from alertissimo.orchestration.binding import bind_endpoint_calls
from alertissimo.orchestration.ir import GetLightcurveStep, LookupStep, Source, TargetSelector, WorkflowIR
from alertissimo.orchestration.planner import (
    PlanningAmbiguityError, PlanningDeferredError, UnsupportedStepError,
    plan_step, plan_workflow,
)
from alertissimo.orchestration.runtime import EndpointPlanRef, WorkflowRun


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def lookup(broker="lasair", origin="ztf", ids=("1",), kind="object"):
    return LookupStep(
        target=TargetSelector(ids=list(ids), kind=kind),
        sources=[Source(broker=broker, origin=origin)],
    )


def local_provider(tmp_path, broker="lasair", origin="ztf"):
    root = tmp_path / "providers"
    destination = root / broker / origin
    shutil.copytree(PROVIDERS_ROOT / broker / origin, destination)
    return root, destination


def edit_yaml(path, update):
    doc = yaml.safe_load(path.read_text())
    update(doc)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


@pytest.mark.parametrize("broker,origin,endpoint,physical,values", [
    ("alerce", "lsst", "query_object", "oid", [1, 2]),
    ("alerce", "ztf", "query_object", "oid", ["1", "2"]),
    ("antares", "lsst", "get_by_lsst_dia_object_id", "lsst_object_id", ["1", "2"]),
    ("antares", "ztf", "get_by_ztf_object_id", "ztf_object_id", ["1", "2"]),
    ("fink", "lsst", "objects", "diaObjectId", ["1,2"]),
    ("fink", "ztf", "objects", "objectId", ["1,2"]),
    ("lasair", "lsst", "object", "objectId", ["1", "2"]),
    ("lasair", "ztf", "objects", "objectIds", ["1,2"]),
])
def test_lookup_plural_targets_preserve_provider_encoding(graph, broker, origin, endpoint, physical, values):
    step = lookup(broker, origin, ("1", "2"))
    run = plan_workflow(WorkflowIR(steps=[step]), graph)
    restored = WorkflowRun.model_validate_json(run.model_dump_json())
    assert restored == run
    plan, = restored.steps[0].endpoint_plans
    assert plan.endpoint == endpoint
    assert plan.semantic_type == "summary"
    assert plan.parameter_sources == {physical: ("target", "ids")}
    calls = bind_endpoint_calls(step, plan, EndpointRegistry())
    assert [call.params[physical] for call in calls] == values


def test_single_object_prefers_the_existing_singular_realization(graph):
    plan, = plan_step(lookup(), graph)
    assert plan.endpoint == "object"


@pytest.mark.parametrize("broker", ["alerce", "antares", "fink", "lasair"])
def test_object_recipes_cannot_accept_alert_ids_even_when_the_endpoint_maps_detections(graph, broker):
    with pytest.raises(UnsupportedStepError):
        plan_step(lookup(broker=broker, kind="alert"), graph)


def test_lookup_selection_does_not_need_operation_tags(tmp_path):
    root, destination = local_provider(tmp_path)
    def remove_tags(doc):
        for endpoint in doc["endpoints"].values():
            endpoint["operation_types"] = []
    edit_yaml(destination / "endpoints.yaml", remove_tags)
    plan, = plan_step(lookup(ids=("1", "2")), build_capability_graph(root))
    assert plan.endpoint == "objects"


def test_equal_lookup_recipes_remain_ambiguous_after_cardinality_preference(tmp_path):
    root, destination = local_provider(tmp_path)
    def duplicate(doc):
        alternatives = doc["recipes"]["lookup"]
        alternatives.append(alternatives[0])
    edit_yaml(destination / "capabilities.yaml", duplicate)
    with pytest.raises(PlanningAmbiguityError, match=r"recipe\[2\]"):
        plan_step(lookup(), build_capability_graph(root))


@pytest.mark.parametrize("kind", [None, "source", "detection", "unknown", 1])
def test_registry_validates_lookup_namespace_with_the_existing_ir(tmp_path, kind):
    root, destination = local_provider(tmp_path)
    def invalid_kind(doc):
        doc["recipes"]["lookup"][0]["target_kind"] = kind
    edit_yaml(destination / "capabilities.yaml", invalid_kind)
    with pytest.raises(CapabilityGraphError, match="valid LookupStep target kind"):
        build_capability_graph(root)


def test_missing_lookup_namespace_is_a_registry_error(tmp_path):
    root, destination = local_provider(tmp_path)
    def omit_kind(doc):
        del doc["recipes"]["lookup"][0]["target_kind"]
    edit_yaml(destination / "capabilities.yaml", omit_kind)
    with pytest.raises(CapabilityGraphError, match="missing keys.*target_kind"):
        build_capability_graph(root)


def test_namespace_guard_is_not_allowed_on_other_operations(tmp_path):
    root, destination = local_provider(tmp_path)
    def misplaced_kind(doc):
        doc["recipes"]["cone_search"][0]["target_kind"] = "object"
    edit_yaml(destination / "capabilities.yaml", misplaced_kind)
    with pytest.raises(CapabilityGraphError, match="unknown keys.*target_kind"):
        build_capability_graph(root)


def test_lookup_with_untranslated_target_input_does_not_fall_back(tmp_path):
    root, destination = local_provider(tmp_path)
    def constant_target(doc):
        for alternative in doc["recipes"]["lookup"]:
            params = alternative["calls"][0]["params"]
            name, = params
            params[name] = {"value": "unrelated-object"}
    edit_yaml(destination / "capabilities.yaml", constant_target)
    with pytest.raises(PlanningDeferredError, match="does not bind the target identities"):
        plan_step(lookup(), build_capability_graph(root))


@pytest.mark.parametrize("columns", [None, "objectId"])
def test_lookup_reuse_requires_matching_request_constants(tmp_path, columns):
    root, destination = local_provider(tmp_path, "fink", "ztf")
    if columns is not None:
        def narrower_lookup(doc):
            doc["recipes"]["lookup"][0]["calls"][0]["params"]["columns"] = {"value": columns}
        edit_yaml(destination / "capabilities.yaml", narrower_lookup)
    step = lookup("fink", "ztf")
    workflow = WorkflowIR(steps=[
        step, GetLightcurveStep(sources=step.sources),
    ])
    run = plan_workflow(workflow, build_capability_graph(root))
    consumer, = run.steps[1].endpoint_plans
    if columns is None:
        assert consumer.execution_reuse_from == EndpointPlanRef(step_index=0, plan_index=0)
    else:
        assert consumer.execution_reuse_from is None
        assert consumer.candidate_input_from.step_index == 0
