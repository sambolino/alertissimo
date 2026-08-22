import pytest

from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import (
    ConfirmClause,
    DSLParseError,
    SurfaceCapabilityStatus,
    compile_surface_to_ir,
    lower_surface,
    parse_surface_script,
    validate_surface_capabilities,
)
from alertissimo.orchestration.ir import ConfirmStep, SemanticSearchStep
from alertissimo.orchestration.planner import PlanningDeferredError, plan_workflow
from alertissimo.orchestration.runtime import CandidateInputRef, MaterialInputRef


def test_confirm_surface_requires_explicit_unique_broker_quorum():
    surface = parse_surface_script(
        "objects from ztf via alerce\n"
        "confirm by 2 via fink, alerce, antares\n"
    )

    clause = surface.clauses[0]
    assert isinstance(clause, ConfirmClause)
    assert clause.required_agreement == 2
    assert clause.brokers == ("fink", "alerce", "antares")

    with pytest.raises(DSLParseError, match="brokers must be unique"):
        parse_surface_script(
            "objects from ztf\nconfirm by 2 via fink, fink\n"
        )
    with pytest.raises(DSLParseError, match="quorum cannot exceed"):
        parse_surface_script(
            "objects from ztf\nconfirm by 3 via fink, alerce\n"
        )


def test_confirm_lowers_to_first_class_existence_step_not_where_predicate_quorum():
    surface = parse_surface_script(
        "objects from ztf via alerce\n"
        "where summary.time.last_mjd > 60000\n"
        "confirm by 2 via fink, lasair, antares\n"
    )
    workflow = lower_surface(surface).workflow

    assert isinstance(workflow.steps[0], SemanticSearchStep)
    confirm = workflow.steps[-1]
    assert isinstance(confirm, ConfirmStep)
    assert confirm.required_agreement == 2
    assert {(source.origin, source.broker) for source in confirm.sources} == {
        ("ztf", "fink"),
        ("ztf", "lasair"),
        ("ztf", "antares"),
    }
    assert not hasattr(confirm, "predicate")


def test_real_ztf_brokers_expose_confirmable_object_evidence():
    graph = build_capability_graph()
    surface = parse_surface_script(
        "objects from ztf via alerce\n"
        "inside (124.87996115142856, -6.0205001, 1arcsec)\n"
        "latest 1\n"
        "confirm by 3 via fink, alerce, lasair, antares\n"
    )

    report = validate_surface_capabilities(surface, graph=graph)
    confirm_checks = [check for check in report.checks if check.subject == "confirm"]

    assert report.status is SurfaceCapabilityStatus.SUPPORTED
    assert len(confirm_checks) == 4
    assert all(check.status is SurfaceCapabilityStatus.SUPPORTED for check in confirm_checks)
    assert {check.broker for check in confirm_checks} == {
        "fink",
        "alerce",
        "lasair",
        "antares",
    }


def test_confirm_becomes_candidate_and_material_owner_for_downstream_steps():
    graph = build_capability_graph()
    workflow = compile_surface_to_ir(
        parse_surface_script(
            "objects from ztf via alerce\n"
            "inside (124.87996115142856, -6.0205001, 1arcsec)\n"
            "latest 1\n"
            "confirm by 3 via fink, alerce, lasair, antares\n"
            "with lightcurve via fink\n"
        ),
        graph=graph,
    )
    run = plan_workflow(workflow, graph)

    confirm = run.steps[1]
    assert isinstance(workflow.steps[1], ConfirmStep)
    assert len(confirm.endpoint_plans) == 4
    assert confirm.candidate_input_from is None
    assert confirm.material_input_from == MaterialInputRef(step_index=0)
    assert all(
        plan.candidate_input_from == CandidateInputRef(step_index=0)
        for plan in confirm.endpoint_plans
    )

    downstream = run.steps[2]
    assert downstream.endpoint_plans[0].candidate_input_from == CandidateInputRef(
        step_index=1
    )
    assert downstream.material_input_from == MaterialInputRef(step_index=1)


def test_singular_confirm_endpoint_requires_latest_one_until_generic_fanout_exists():
    graph = build_capability_graph()
    workflow = compile_surface_to_ir(
        parse_surface_script(
            "objects from ztf via alerce\n"
            "inside (124.87996115142856, -6.0205001, 5arcsec)\n"
            "confirm by 1 via antares\n"
        ),
        graph=graph,
    )

    with pytest.raises(PlanningDeferredError, match="latest 1"):
        plan_workflow(workflow, graph)
