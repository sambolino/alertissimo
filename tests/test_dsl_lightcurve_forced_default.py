"""Contracts for provisional forced-photometry inclusion in ``with lightcurve``."""

import pytest

from alertissimo.data_layer.execution import EndpointRegistry
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import SurfaceLoweringError, compile_surface, parse_surface_script
from alertissimo.orchestration.binding import bind_workflow_run
from alertissimo.orchestration.ir import GetLightcurveStep, Source, TargetSelector, WorkflowIR
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import CandidateInputRef


DSL = """objects from lsst via fink
    inside (124.87996115142856, -6.0205001, 5arcsec)
    with lightcurve via fink
"""


def test_with_lightcurve_stays_one_semantic_step_but_plans_fink_sources_and_fp():
    graph = build_capability_graph()
    compilation = compile_surface(parse_surface_script(DSL), graph=graph)

    assert [step.op for step in compilation.workflow.steps] == [
        "cone_search",
        "get_lightcurve",
    ]
    assert sum(
        step.op == "get_lightcurve" for step in compilation.workflow.steps
    ) == 1
    assert all(
        step.op != "get_forced_photometry" for step in compilation.workflow.steps
    )

    run = plan_workflow(compilation.workflow, graph)
    lightcurve_run = run.steps[1]

    assert [plan.endpoint for plan in lightcurve_run.endpoint_plans] == [
        "sources",
        "fp",
    ]
    assert [plan.candidate_input_from for plan in lightcurve_run.endpoint_plans] == [
        CandidateInputRef(step_index=0),
        CandidateInputRef(step_index=0),
    ]


def test_explicit_target_binds_same_objects_to_primary_and_forced_supplement():
    graph = build_capability_graph()
    workflow = WorkflowIR(
        steps=[
            GetLightcurveStep(
                target=TargetSelector(ids=["A", "B"], kind="object"),
                sources=[Source(broker="fink", origin="lsst")],
            )
        ]
    )
    run = plan_workflow(workflow, graph)
    bindings = bind_workflow_run(run, EndpointRegistry())

    assert [call.endpoint_plan.endpoint for call in bindings[0].bound_calls] == [
        "sources",
        "fp",
    ]
    assert [call.params for call in bindings[0].bound_calls] == [
        {"diaObjectId": "A,B"},
        {"diaObjectId": "A,B"},
    ]


def test_standalone_forced_photometry_surface_requirement_remains_unsupported():
    graph = build_capability_graph()
    source = """objects from lsst via fink
    with forced_photometry via fink
"""

    with pytest.raises(SurfaceLoweringError) as caught:
        compile_surface(parse_surface_script(source), graph=graph)

    assert caught.value.code == "ontology_unknown_requirement_product"
