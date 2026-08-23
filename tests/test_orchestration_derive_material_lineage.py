"""Planner contracts for occurrence-owned DeriveStep material views."""

from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.orchestration.ir import (
    ColorColorStep,
    ColorMagnitudeStep,
    ConeSearchStep,
    GetLightcurveStep,
    SearchSelection,
    Source,
    TargetSelector,
    WorkflowIR,
)
from alertissimo.orchestration.planner import plan_workflow


def test_direct_get_then_consecutive_derivations_chain_material_ownership():
    workflow = WorkflowIR(
        steps=[
            GetLightcurveStep(
                target=TargetSelector(ids=["ZTF18abbuksn"], kind="object"),
                sources=[Source(broker="fink", origin="ztf")],
            ),
            ColorMagnitudeStep(
                color="g-r",
                magnitude_field="photometry.r.psf.mag",
            ),
            ColorColorStep(color_x="g-r", color_y="r-i"),
        ]
    )

    run = plan_workflow(workflow, build_capability_graph())

    assert run.steps[1].material_input_from is not None
    assert run.steps[1].material_input_from.step_index == 0
    assert run.steps[2].material_input_from is not None
    assert run.steps[2].material_input_from.step_index == 1
    assert run.steps[1].candidate_input_from is None
    assert run.steps[2].candidate_input_from is None
    assert run.steps[1].endpoint_plans == ()
    assert run.steps[2].endpoint_plans == ()


def test_derive_advances_material_but_not_candidate_binding_owner():
    workflow = WorkflowIR(
        steps=[
            ConeSearchStep(
                semantic_type="summary",
                ra=124.87996115142856,
                dec=-6.0205001,
                radius=5.0,
                selection=SearchSelection(latest=1),
                sources=[Source(broker="alerce", origin="ztf")],
            ),
            GetLightcurveStep(
                sources=[Source(broker="fink", origin="ztf")],
            ),
            ColorMagnitudeStep(
                color="g-r",
                magnitude_field="photometry.r.psf.mag",
            ),
            GetLightcurveStep(
                sources=[Source(broker="lasair", origin="ztf")],
            ),
        ]
    )

    run = plan_workflow(workflow, build_capability_graph())

    first_get_plan = run.steps[1].endpoint_plans[0]
    assert first_get_plan.candidate_input_from is not None
    assert first_get_plan.candidate_input_from.step_index == 0
    assert run.steps[1].material_input_from is not None
    assert run.steps[1].material_input_from.step_index == 0

    assert run.steps[2].material_input_from is not None
    assert run.steps[2].material_input_from.step_index == 1
    assert run.steps[2].candidate_input_from is None

    final_get_plan = run.steps[3].endpoint_plans[0]
    assert final_get_plan.candidate_input_from is not None
    assert final_get_plan.candidate_input_from.step_index == 0
    assert run.steps[3].material_input_from is not None
    assert run.steps[3].material_input_from.step_index == 2
