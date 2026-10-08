"""Active atomic cone recipes preserve physical encoding and migration boundaries."""

from dataclasses import replace
from datetime import timedelta
import shutil

import pytest
import yaml

from alertissimo.data_layer.execution import EndpointRegistry
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.data_layer.transforms import request as request_transforms
from alertissimo.orchestration.binding import bind_endpoint
from alertissimo.orchestration.ir import ConeSearchStep, Source, TimeContext, WorkflowIR
from alertissimo.orchestration.planner import (
    PlanningAmbiguityError, PlanningDeferredError, UnsupportedStepError,
    plan_step, plan_workflow,
)
from alertissimo.orchestration.runtime import WorkflowRun
from alertissimo.orchestration.validation import validate_step_capabilities


SCALAR_CONES = (
    ("alerce", "lsst", "query_objects"), ("alerce", "ztf", "query_objects"),
    ("fink", "lsst", "conesearch"), ("fink", "ztf", "conesearch"),
    ("lasair", "lsst", "cone"), ("lasair", "ztf", "cone"),
)


def cone(broker="fink", origin="ztf", **kwargs):
    return ConeSearchStep(
        semantic_type="summary", ra=120, dec=-6, radius=30,
        sources=[Source(broker=broker, origin=origin)], **kwargs,
    )


def local_provider(tmp_path, broker="fink", origin="ztf"):
    root = tmp_path / "providers"
    destination = root / broker / origin
    shutil.copytree(PROVIDERS_ROOT / broker / origin, destination)
    return root, destination


def edit_yaml(path, update):
    document = yaml.safe_load(path.read_text())
    update(document)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


@pytest.mark.parametrize("broker, origin, endpoint", SCALAR_CONES)
def test_active_scalar_cones_keep_their_coordinates_and_endpoint(broker, origin, endpoint):
    step = cone(broker, origin)
    plans = plan_step(step, build_capability_graph())
    assert plans[0].endpoint == endpoint
    assert plans[0].parameter_sources == {
        "ra": ("ra",), "dec": ("dec",), "radius": ("radius",),
    }
    call = bind_endpoint(step, plans[0], EndpointRegistry())
    assert call.params == {"ra": 120, "dec": -6, "radius": 30}
    assert [plan.endpoint for plan in plans] == (
        ["cone", "query"] if (broker, origin) == ("lasair", "ztf") else [endpoint]
    )


@pytest.mark.parametrize("origin", ["lsst", "ztf"])
def test_antares_recipe_uses_existing_native_encoders(monkeypatch, origin):
    graph = build_capability_graph()
    def encoder(path):
        if path.endswith(":skycoord_icrs_degrees"):
            return lambda **values: ("center", values["ra"], values["dec"])
        return lambda **values: ("radius", values["radius"])
    monkeypatch.setattr(request_transforms, "load_binding_adapter", encoder)
    step = cone("antares", origin)
    plan, = plan_step(step, graph)
    assert plan.parameter_sources["center"] == {"ra": ("ra",), "dec": ("dec",)}
    assert bind_endpoint(step, plan, EndpointRegistry()).params == {
        "center": ("center", 120, -6), "radius": ("radius", 30),
    }


def test_recipe_selection_and_binding_do_not_need_legacy_tags_or_scalar_bind_roles(tmp_path):
    root, destination = local_provider(tmp_path)
    def remove_legacy(doc):
        endpoint = doc["endpoints"]["conesearch"]
        endpoint["operation_types"] = []
        for name in ("ra", "dec", "radius"):
            endpoint["params"][name].pop("bind")
    edit_yaml(destination / "endpoints.yaml", remove_legacy)
    graph = build_capability_graph(root)
    step = cone()
    assert validate_step_capabilities(step, graph).status == "supported"
    plan, = plan_step(step, graph)
    assert bind_endpoint(step, plan, EndpointRegistry(root)).params == {
        "ra": 120, "dec": -6, "radius": 30,
    }


def test_infeasible_recipe_does_not_fall_back_to_a_tagged_endpoint(tmp_path):
    root, destination = local_provider(tmp_path, "alerce", "lsst")
    def omit_radius(doc):
        del doc["recipes"]["cone_search"][0]["calls"][0]["params"]["radius"]
    edit_yaml(destination / "capabilities.yaml", omit_radius)
    with pytest.raises(PlanningDeferredError, match="canonical cone coordinates"):
        plan_step(cone("alerce", "lsst"), build_capability_graph(root))


def test_equal_recipes_stay_ambiguous_even_with_the_same_endpoint(tmp_path):
    root, destination = local_provider(tmp_path)
    def duplicate(doc):
        alternatives = doc["recipes"]["cone_search"]
        alternatives.append(alternatives[0])
    edit_yaml(destination / "capabilities.yaml", duplicate)
    with pytest.raises(PlanningAmbiguityError, match=r"recipe\[1\]"):
        plan_step(cone(), build_capability_graph(root))


@pytest.mark.parametrize("kwargs", [
    {"magnitude_limit": 20}, {"time_context": TimeContext(window=timedelta(days=1))},
    {"criteria": {"untranslated": True}},
])
def test_untranslated_optional_cone_inputs_are_deferred(kwargs):
    with pytest.raises(PlanningDeferredError, match="no declared translation"):
        plan_step(cone(**kwargs), build_capability_graph())


def test_record_mismatch_and_unconstrained_ambiguity_are_preserved():
    graph = build_capability_graph()
    missing = cone().model_copy(update={"semantic_type": "spectrum"})
    with pytest.raises(UnsupportedStepError):
        plan_step(missing, graph)
    with pytest.raises(PlanningAmbiguityError):
        plan_step(cone().model_copy(update={"sources": []}), graph)
    legacy = replace(graph, recipe_capabilities=())
    legacy_plan, = plan_step(cone(), legacy)
    assert legacy_plan.parameter_sources is None


def test_recipe_plan_survives_runtime_json_round_trip():
    workflow = WorkflowIR(steps=[cone("fink", "lsst")])
    run = plan_workflow(workflow, build_capability_graph())
    assert WorkflowRun.model_validate_json(run.model_dump_json()) == run


def test_physical_boolean_constant_reaches_binder_without_a_legacy_bind_role(tmp_path):
    root, destination = local_provider(tmp_path, "alerce", "lsst")
    def add_constant(doc):
        doc["recipes"]["cone_search"][0]["calls"][0]["params"]["count"] = {"value": False}
    edit_yaml(destination / "capabilities.yaml", add_constant)
    step = cone("alerce", "lsst")
    plan, = plan_step(step, build_capability_graph(root))
    assert plan.request_params == {"count": False}
    assert "count" not in plan.parameter_sources
    assert bind_endpoint(step, plan, EndpointRegistry(root)).params == {
        "ra": 120, "dec": -6, "radius": 30, "count": False,
    }
