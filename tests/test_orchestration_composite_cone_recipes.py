"""Cone composites follow declarations and retain candidate dependency semantics."""

from dataclasses import replace
import shutil

import pytest
import yaml

from alertissimo.data_layer.execution import EndpointRegistry
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.orchestration.binding import bind_endpoint_calls
from alertissimo.orchestration.ir import ConeSearchStep, Source, WorkflowIR
from alertissimo.orchestration.planner import (
    PlanningDeferredError, UnsupportedStepError, plan_step, plan_workflow,
)
from alertissimo.orchestration.runtime import WorkflowRun
from alertissimo.orchestration.validation import validate_step_capabilities


def cone(*sources, semantic_type="summary"):
    return ConeSearchStep(
        semantic_type=semantic_type, ra=120, dec=-6, radius=30,
        sources=list(sources) or [Source(broker="lasair", origin="ztf")],
    )


def local_provider(tmp_path):
    root = tmp_path / "providers"
    destination = root / "lasair" / "ztf"
    shutil.copytree(PROVIDERS_ROOT / "lasair" / "ztf", destination)
    return root, destination


def edit_yaml(path, update):
    document = yaml.safe_load(path.read_text())
    update(document)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def test_composite_uses_authored_endpoint_names_parameters_and_constants(tmp_path):
    root, destination = local_provider(tmp_path)
    renames = {"cone": "discovery", "query": "enrichment"}
    def endpoints(doc):
        for old, new in renames.items():
            doc["endpoints"][new] = doc["endpoints"].pop(old)
        params = doc["endpoints"]["enrichment"]["params"]
        params["constraint"] = params.pop("conditions")
    def mappings(doc):
        for payload in doc["payloads"].values():
            payload["endpoint"] = renames.get(payload["endpoint"], payload["endpoint"])
    def recipes(doc):
        calls = doc["recipes"]["cone_search"][0]["calls"]
        for call in calls:
            call["endpoint"] = renames[call["endpoint"]]
        params = calls[1]["params"]
        params["constraint"] = params.pop("conditions")
        params["offset"] = {"value": 7}
        calls[1]["required"] = True
    edit_yaml(destination / "endpoints.yaml", endpoints)
    edit_yaml(destination / "mappings.yaml", mappings)
    edit_yaml(destination / "capabilities.yaml", recipes)

    step = cone()
    plans = plan_step(step, build_capability_graph(root))
    assert [plan.endpoint for plan in plans] == ["discovery", "enrichment"]
    assert plans[1].required is True
    bound, = bind_endpoint_calls(
        step, plans[1], EndpointRegistry(root),
        runtime_values={"target_id": ("ZTF20acpwljl",)},
    )
    assert bound.params["constraint"] == 'objects.objectId IN ("ZTF20acpwljl")'
    assert bound.params["offset"] == 7


def test_dependency_indexes_account_for_previous_source_plans_and_survive_json():
    step = cone(Source(broker="fink", origin="ztf"), Source(broker="lasair", origin="ztf"))
    run = plan_workflow(WorkflowIR(steps=[step]), build_capability_graph())
    restored = WorkflowRun.model_validate_json(run.model_dump_json())
    assert restored == run
    plans = restored.steps[0].endpoint_plans
    assert [plan.endpoint for plan in plans] == ["conesearch", "cone", "query"]
    assert plans[2].candidate_input_from_plan.plan_index == 1
    assert plans[2].parameter_sources == {"conditions": "target_id"}
    call, = bind_endpoint_calls(
        step, plans[2], EndpointRegistry(),
        runtime_values={"target_id": ("ZTF20acpwljl",)},
    )
    assert call.params["conditions"] == 'objects.objectId IN ("ZTF20acpwljl")'


def test_optional_output_mapping_does_not_prove_requested_discovery_family(tmp_path):
    root, destination = local_provider(tmp_path)
    def add_optional_mapping(doc):
        doc["mappings"]["classification@sherlock:lasair.best.class"].append("query#classification")
    edit_yaml(destination / "mappings.yaml", add_optional_mapping)
    graph = build_capability_graph(root)
    assert graph.fields_for_endpoint("lasair", "ztf", "query", semantic_record_noun="classification")
    result = validate_step_capabilities(cone(semantic_type="classification"), graph)
    assert result.status == "unsupported"
    assert result.candidates == ()


def test_follow_up_is_not_invented_for_atomic_or_legacy_cone(tmp_path):
    root, destination = local_provider(tmp_path)
    def atomic(doc):
        doc["recipes"]["cone_search"][0]["calls"].pop()
    edit_yaml(destination / "capabilities.yaml", atomic)
    graph = build_capability_graph(root)
    assert [plan.endpoint for plan in plan_step(cone(), graph)] == ["cone"]
    legacy = replace(graph, recipe_capabilities=())
    with pytest.raises(UnsupportedStepError):
        plan_step(cone(), legacy)
    # Compatibility routing requires an explicit tag; production Lasair ZTF
    # cone routing now belongs to its recipe.
    legacy = replace(legacy, endpoint_capabilities=tuple(
        replace(endpoint, operation_types=("cone_search",))
        if endpoint.endpoint == "cone" else endpoint
        for endpoint in legacy.endpoint_capabilities
    ))
    assert [plan.endpoint for plan in plan_step(cone(), legacy)] == ["cone"]


def test_unsupported_composite_shape_is_deferred_without_legacy_fallback(tmp_path):
    root, destination = local_provider(tmp_path)
    def add_independent_call(doc):
        calls = doc["recipes"]["cone_search"][0]["calls"]
        calls.append(calls[0].copy())
    edit_yaml(destination / "capabilities.yaml", add_independent_call)
    with pytest.raises(PlanningDeferredError, match="consume the discovery identities"):
        plan_step(cone(), build_capability_graph(root))
