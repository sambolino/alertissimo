"""Targeted crossmatch recipes keep catalog evidence and radius intent distinct."""

from dataclasses import replace
import shutil

import pytest
import yaml

from alertissimo.data_layer.execution import EndpointRegistry
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.runtime.capability_graph import (
    EndpointCapability, SemanticRecordCapability, build_capability_graph,
)
from alertissimo.orchestration.binding import bind_endpoint_calls
from alertissimo.orchestration.ir import (
    FilterStep, GetCrossmatchStep, LookupStep, Source, TargetSelector, WorkflowIR,
)
from alertissimo.orchestration.planner import (
    PlanningAmbiguityError, PlanningDeferredError, UnsupportedStepError,
    plan_step, plan_workflow,
)
from alertissimo.orchestration.runtime import CandidateInputRef, EndpointPlanRef, WorkflowRun
from alertissimo.orchestration.validation import validate_step_capabilities


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def crossmatch(broker="fink", origin="ztf", catalog="panstarrs", ids=("1", "2"), radius=None):
    return GetCrossmatchStep(
        target=TargetSelector(ids=list(ids), kind="object") if ids is not None else None,
        catalog=catalog, radius=radius, sources=[Source(broker=broker, origin=origin)],
    )


def local_provider(tmp_path, broker="fink", origin="ztf"):
    root = tmp_path / "providers"
    destination = root / broker / origin
    shutil.copytree(PROVIDERS_ROOT / broker / origin, destination)
    return root, destination


def edit_yaml(path, update):
    doc = yaml.safe_load(path.read_text())
    update(doc)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


@pytest.mark.parametrize("broker,origin,catalog,endpoint,physical,values", [
    ("antares", "ztf", "gaia", "get_by_ztf_object_id", "ztf_object_id", ["1", "2"]),
    ("antares", "lsst", "gaia", "get_by_lsst_dia_object_id", "lsst_object_id", ["1", "2"]),
    ("fink", "ztf", "PANSTARRS", "objects", "objectId", ["1,2"]),
    ("fink", "lsst", "gaia", "sources", "diaObjectId", ["1,2"]),
    ("lasair", "ztf", "tns", "objects", "objectIds", ["1,2"]),
    ("lasair", "lsst", "tns", "object", "objectId", ["1", "2"]),
])
def test_catalog_eligible_recipes_preserve_provider_target_encoding(
    graph, broker, origin, catalog, endpoint, physical, values,
):
    step = crossmatch(broker, origin, catalog)
    run = plan_workflow(WorkflowIR(steps=[step]), graph)
    restored = WorkflowRun.model_validate_json(run.model_dump_json())
    assert restored == run
    plan, = restored.steps[0].endpoint_plans
    assert plan.endpoint == endpoint
    assert plan.parameter_sources == {physical: ("target", "ids")}
    calls = bind_endpoint_calls(step, plan, EndpointRegistry())
    assert [call.params[physical] for call in calls] == values
    assert all("catalog" not in call.params and "radius" not in call.params for call in calls)


@pytest.mark.parametrize("origin", ["ztf", "lsst"])
def test_dynamic_lasair_catalogs_remain_deferred(graph, origin):
    with pytest.raises(PlanningDeferredError, match="dynamic producer mapping"):
        plan_step(crossmatch("lasair", origin, "gaia"), graph)


@pytest.mark.parametrize("origin", ["ztf", "lsst"])
def test_alerce_does_not_acquire_crossmatch_capability_from_other_material(graph, origin):
    with pytest.raises(UnsupportedStepError):
        plan_step(crossmatch("alerce", origin, "gaia"), graph)


def test_catalogs_are_not_inherited_from_other_endpoints(graph):
    # Fink/ZTF latest/anomaly responses map Gaia DR3; objects does not.
    with pytest.raises(UnsupportedStepError, match="gaia_dr3"):
        plan_step(crossmatch(catalog="gaia_dr3"), graph)


def test_unqualified_lasair_retrieval_keeps_real_ambiguity(graph):
    with pytest.raises(PlanningAmbiguityError):
        plan_step(crossmatch("lasair", "ztf", None), graph)
    plan, = plan_step(crossmatch("lasair", "lsst", None), graph)
    assert plan.endpoint == "sherlock_object"


def test_fresh_retrievals_require_object_bindings_even_without_explicit_targets(graph):
    for broker in ("antares", "fink", "lasair"):
        for origin in ("ztf", "lsst"):
            result = validate_step_capabilities(crossmatch(broker, origin, None, ids=None), graph)
            assert result.status == "supported"
            assert all("target_id" in endpoint.binding_roles for endpoint in result.candidates)
            assert all(source_result.recipes for source_result in result.source_results)


def test_crossmatch_recipe_selection_does_not_need_operation_tags(tmp_path):
    root, destination = local_provider(tmp_path)
    def remove_tags(doc):
        for endpoint in doc["endpoints"].values():
            endpoint["operation_types"] = []
    edit_yaml(destination / "endpoints.yaml", remove_tags)
    plan, = plan_step(crossmatch(), build_capability_graph(root))
    assert plan.endpoint == "objects"


def test_dynamic_catalog_parameter_existence_is_not_wildcard_proof(tmp_path):
    root, destination = local_provider(tmp_path, "lasair", "lsst")
    def add_parameter(doc):
        endpoint = doc["endpoints"]["sherlock_object"]
        endpoint["params"]["catalog"] = {"type": "string"}
        endpoint["server_filters"].append("catalog")
    edit_yaml(destination / "endpoints.yaml", add_parameter)
    with pytest.raises(PlanningDeferredError, match="dynamic producer mapping"):
        plan_step(crossmatch("lasair", "lsst", "gaia"), build_capability_graph(root))


@pytest.mark.parametrize("translated,server_filter", [(False, True), (True, False), (True, True)])
def test_radius_needs_a_recipe_assignment_and_server_filter_evidence(tmp_path, translated, server_filter):
    root, destination = local_provider(tmp_path)
    def add_radius(doc):
        endpoint = doc["endpoints"]["objects"]
        endpoint["params"]["match_radius"] = {"type": "number"}
        if server_filter:
            endpoint["server_filters"].append("match_radius")
        endpoint["operation_types"].append("catalog_crossmatch")
    edit_yaml(destination / "endpoints.yaml", add_radius)
    if translated:
        def assign_radius(doc):
            doc["recipes"]["get_crossmatch"][0]["calls"][0]["params"]["match_radius"] = {"from": "step.radius"}
        edit_yaml(destination / "capabilities.yaml", assign_radius)
    step = crossmatch(radius=1.5)
    compiled = build_capability_graph(root)
    if not (translated and server_filter):
        with pytest.raises(UnsupportedStepError, match="requested radius"):
            plan_step(step, compiled)
    else:
        plan, = plan_step(step, compiled)
        assert plan.parameter_sources["match_radius"] == ("radius",)
        calls = bind_endpoint_calls(step, plan, EndpointRegistry(root))
        assert calls[0].params["match_radius"] == 1.5


def test_invalid_target_assignment_cannot_fall_back_to_tags(tmp_path):
    root, destination = local_provider(tmp_path)
    def constant_identity(doc):
        doc["recipes"]["get_crossmatch"][0]["calls"][0]["params"]["objectId"] = {"value": "unrelated"}
    edit_yaml(destination / "capabilities.yaml", constant_identity)
    with pytest.raises(PlanningDeferredError, match="does not bind the target identities"):
        plan_step(crossmatch(), build_capability_graph(root))


def test_duplicate_crossmatch_recipes_remain_ambiguous(tmp_path):
    root, destination = local_provider(tmp_path)
    def duplicate(doc):
        recipes = doc["recipes"]["get_crossmatch"]
        recipes.append(recipes[0])
    edit_yaml(destination / "capabilities.yaml", duplicate)
    with pytest.raises(PlanningAmbiguityError, match=r"recipe\[1\]"):
        plan_step(crossmatch(), build_capability_graph(root))


@pytest.mark.parametrize("filtered", [False, True])
def test_candidate_population_preserves_reuse_or_late_binding(graph, filtered):
    get = crossmatch(ids=None)
    steps = [LookupStep(target=TargetSelector(ids=["1", "2"], kind="object"), sources=get.sources)]
    if filtered:
        steps.append(FilterStep(criteria={}))
    steps.append(get)
    run = plan_workflow(WorkflowIR(steps=steps), graph)
    restored = WorkflowRun.model_validate_json(run.model_dump_json())
    assert restored == run
    plan, = restored.steps[-1].endpoint_plans
    if filtered:
        assert plan.execution_reuse_from is None
        assert plan.candidate_input_from == CandidateInputRef(step_index=1)
        calls = bind_endpoint_calls(get, plan, EndpointRegistry(), runtime_values={"target_id": ["2"]})
        assert calls[0].params["objectId"] == "2"
    else:
        assert plan.execution_reuse_from == EndpointPlanRef(step_index=0, plan_index=0)


def test_unmigrated_candidates_still_receive_catalog_and_radius_checks(tmp_path):
    root, _ = local_provider(tmp_path, origin="lsst")
    graph = build_capability_graph(root)
    endpoint = EndpointCapability(
        "legacy", "survey", "context", "/context", "GET", ("context_lookup",),
        ("object_id", "radius"), ("object_id", "radius"), None, False, "object",
        ("target_id",), (),
    )
    graph = replace(
        graph, endpoint_capabilities=graph.endpoint_capabilities + (endpoint,),
        semantic_record_capabilities=graph.semantic_record_capabilities + (
            SemanticRecordCapability("legacy", "survey", "crossmatch@erosita:legacy", ("context",), ()),
        ),
    )
    step = crossmatch(origin="lsst", catalog="gaia", ids=("1",)).model_copy(update={"sources": []})
    result = validate_step_capabilities(step, graph)
    assert {candidate.endpoint for candidate in result.candidates} == {"sources"}
    with pytest.raises(UnsupportedStepError, match="requested radius"):
        plan_step(step.model_copy(update={"radius": 1.5}), graph)
