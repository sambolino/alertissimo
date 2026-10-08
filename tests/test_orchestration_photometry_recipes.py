"""Declared photometry retrievals keep physical encoding and workflow lineage."""

from dataclasses import replace
from datetime import timedelta
import shutil

import pytest
import yaml

from alertissimo.data_layer.execution import EndpointRegistry
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.runtime.capability_graph import CapabilityGraphError, build_capability_graph
from alertissimo.orchestration.binding import bind_endpoint_calls
from alertissimo.orchestration.ir import (
    ConeSearchStep, GetForcedPhotometryStep, GetLightcurveStep,
    Source, TargetSelector, TimeContext, WorkflowIR,
)
from alertissimo.orchestration.planner import PlanningDeferredError, UnsupportedStepError, plan_step, plan_workflow
from alertissimo.orchestration.runtime import CandidateInputRef, EndpointPlanRef, WorkflowRun


def retrieval(broker="fink", origin="lsst", ids=("1", "2"), **kwargs):
    return GetLightcurveStep(
        sources=[Source(broker=broker, origin=origin)],
        target=TargetSelector(ids=list(ids), kind="object") if ids else None,
        **kwargs,
    )


def local_provider(tmp_path, broker="fink", origin="lsst"):
    root = tmp_path / "providers"
    destination = root / broker / origin
    shutil.copytree(PROVIDERS_ROOT / broker / origin, destination)
    return root, destination


def edit_yaml(path, update):
    doc = yaml.safe_load(path.read_text())
    update(doc)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


@pytest.mark.parametrize("broker,origin,endpoints,physical", [
    ("alerce", "lsst", ["query_lightcurve"], "oid"),
    ("alerce", "ztf", ["query_lightcurve"], "oid"),
    ("antares", "lsst", ["get_by_lsst_dia_object_id"], "lsst_object_id"),
    ("antares", "ztf", ["get_by_ztf_object_id"], "ztf_object_id"),
    ("fink", "lsst", ["sources", "fp"], "diaObjectId"),
    ("fink", "ztf", ["objects"], "objectId"),
    ("lasair", "lsst", ["object"], "objectId"),
    ("lasair", "ztf", ["lightcurves"], "objectIds"),
])
def test_plural_target_binding_keeps_provider_encoding_and_supplement_policy(broker, origin, endpoints, physical):
    step = retrieval(broker, origin)
    plans = plan_step(step, build_capability_graph())
    assert [plan.endpoint for plan in plans] == endpoints
    calls = bind_endpoint_calls(step, plans[0], EndpointRegistry())
    if (broker, origin) in {("alerce", "lsst"), ("alerce", "ztf"), ("antares", "lsst"), ("antares", "ztf"), ("lasair", "lsst")}:
        assert [call.params[physical] for call in calls] == ([1, 2] if (broker, origin) == ("alerce", "lsst") else ["1", "2"])
    else:
        assert [call.params[physical] for call in calls] == ["1,2"]
    if len(plans) > 1:
        assert plans[1].required is False


@pytest.mark.parametrize("kwargs", [
    {"bands": ["g"]}, {"time_context": TimeContext(window=timedelta(days=1))},
])
@pytest.mark.parametrize("step_type", [GetLightcurveStep, GetForcedPhotometryStep])
def test_untranslated_requested_constraints_defer_instead_of_falling_back(step_type, kwargs):
    step = step_type(sources=[Source(broker="fink", origin="lsst")], **kwargs)
    with pytest.raises(PlanningDeferredError, match="no declared translation"):
        plan_step(step, build_capability_graph())


def test_targetless_recipe_plans_retain_candidate_owner_and_json_binding():
    source = Source(broker="fink", origin="lsst")
    workflow = WorkflowIR(steps=[
        ConeSearchStep(semantic_type="summary", ra=120, dec=-6, radius=30, sources=[source]),
        GetLightcurveStep(sources=[source]),
    ])
    run = plan_workflow(workflow, build_capability_graph())
    restored = WorkflowRun.model_validate_json(run.model_dump_json())
    assert restored == run
    for plan in restored.steps[1].endpoint_plans:
        assert plan.candidate_input_from == CandidateInputRef(step_index=0)
        bound, = bind_endpoint_calls(workflow.steps[1], plan, EndpointRegistry(), runtime_values={"target_id": ("1", "2")})
        assert bound.params == {"diaObjectId": "1,2"}


def test_optional_singular_supplement_is_retained_only_for_one_explicit_target():
    graph = build_capability_graph()
    for ids, expected in [(("1",), ["query_lightcurve", "query_forced_photometry"]), (("1", "2"), ["query_lightcurve"]), (None, ["query_lightcurve"])]:
        assert [plan.endpoint for plan in plan_step(retrieval("alerce", "lsst", ids), graph)] == expected


def test_recipe_selection_and_forced_reuse_do_not_need_operation_tags(tmp_path):
    root, destination = local_provider(tmp_path)
    def remove_tags(doc):
        for endpoint in doc["endpoints"].values():
            endpoint["operation_types"] = []
    edit_yaml(destination / "endpoints.yaml", remove_tags)
    target = TargetSelector(ids=["1"], kind="object")
    sources = [Source(broker="fink", origin="lsst")]
    workflow = WorkflowIR(steps=[
        GetForcedPhotometryStep(target=target, sources=sources),
        GetLightcurveStep(target=target, sources=sources),
    ])
    graph = build_capability_graph(root)
    run = plan_workflow(workflow, graph)
    assert [plan.endpoint for plan in run.steps[1].endpoint_plans] == ["sources", "fp"]
    assert run.steps[1].endpoint_plans[1].execution_reuse_from == EndpointPlanRef(step_index=0, plan_index=0)
    legacy = replace(graph, recipe_capabilities=())
    with pytest.raises(UnsupportedStepError):
        plan_step(retrieval(), legacy)


def test_untranslated_optional_call_does_not_block_a_translated_primary(tmp_path):
    root, destination = local_provider(tmp_path)
    def physical_band_contract(doc):
        doc["endpoints"]["sources"]["params"]["filter"] = {
            "type": "string", "bind": "bands", "binding": {"collection": "csv"},
        }
    def translated_primary(doc):
        doc["recipes"]["get_lightcurve"][0]["calls"][0]["params"]["filter"] = {"from": "step.bands"}
    edit_yaml(destination / "endpoints.yaml", physical_band_contract)
    edit_yaml(destination / "capabilities.yaml", translated_primary)
    step = retrieval(bands=["g", "r"])
    plan, = plan_step(step, build_capability_graph(root))
    call, = bind_endpoint_calls(step, plan, EndpointRegistry(root))
    assert call.params == {"diaObjectId": "1,2", "filter": "g,r"}


def test_wrong_required_input_does_not_fall_back_to_a_tagged_endpoint(tmp_path):
    root, destination = local_provider(tmp_path)
    def wrong_target_source(doc):
        doc["recipes"]["get_lightcurve"][0]["calls"][0]["params"]["diaObjectId"] = {"from": "step.bands"}
    edit_yaml(destination / "capabilities.yaml", wrong_target_source)
    with pytest.raises(PlanningDeferredError, match="does not bind the target identities"):
        plan_step(retrieval(), build_capability_graph(root))


def test_forced_reuse_requires_the_same_physical_request_constants(tmp_path):
    root, destination = local_provider(tmp_path)
    def narrower_explicit_forced(doc):
        doc["recipes"]["get_forced_photometry"][0]["calls"][0]["params"]["columns"] = {"value": "diaObjectId"}
    edit_yaml(destination / "capabilities.yaml", narrower_explicit_forced)
    target = TargetSelector(ids=["1"], kind="object")
    sources = [Source(broker="fink", origin="lsst")]
    workflow = WorkflowIR(steps=[
        GetForcedPhotometryStep(target=target, sources=sources),
        GetLightcurveStep(target=target, sources=sources),
    ])
    run = plan_workflow(workflow, build_capability_graph(root))
    assert run.steps[1].endpoint_plans[1].execution_reuse_from is None


def test_target_source_requires_the_endpoint_target_encoder_contract(tmp_path):
    root, destination = local_provider(tmp_path)
    def remove_target_role(doc):
        doc["endpoints"]["sources"]["params"]["diaObjectId"].pop("bind")
    edit_yaml(destination / "endpoints.yaml", remove_target_role)
    with pytest.raises(CapabilityGraphError, match="target_id encoder role"):
        build_capability_graph(root)
