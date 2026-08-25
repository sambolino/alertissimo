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
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import CandidateInputRef, MaterialInputRef
from alertissimo.orchestration.validation import validate_step_capabilities


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


def test_adjacent_where_attaches_its_canonical_predicate_to_confirm():
    surface = parse_surface_script(
        "objects from ztf via alerce\n"
        'where classification.best.class = "SN"\n'
        "confirm by 2 via fink, lasair\n"
    )
    workflow = lower_surface(surface).workflow

    assert [step.op for step in workflow.steps] == ["semantic_search", "confirm"]
    search = workflow.steps[0]
    assert isinstance(search, SemanticSearchStep)
    confirm = next(step for step in workflow.steps if isinstance(step, ConfirmStep))
    assert confirm.predicate == search.predicate
    assert confirm.required_agreement == 2
    assert {(source.origin, source.broker) for source in confirm.sources} == {
        ("ztf", "fink"),
        ("ztf", "lasair"),
    }


def test_nonadjacent_where_does_not_turn_later_confirm_into_predicate_quorum():
    surface = parse_surface_script(
        "objects from ztf via alerce\n"
        'where classification.best.class = "SN"\n'
        "latest 1\n"
        "confirm by 2 via fink, lasair\n"
    )
    workflow = lower_surface(surface).workflow

    assert [step.op for step in workflow.steps] == [
        "semantic_search",
        "get_classification",
        "confirm",
    ]
    search = workflow.steps[0]
    assert isinstance(search, SemanticSearchStep)
    assert search.predicate is not None
    confirm = next(step for step in workflow.steps if isinstance(step, ConfirmStep))
    assert confirm.predicate is None


def test_predicate_confirm_requires_broker_endpoint_that_can_materialize_predicate():
    graph = build_capability_graph()
    workflow = lower_surface(
        parse_surface_script(
            "objects from ztf via alerce\n"
            'where classification.best.class = "SN"\n'
            "confirm by 2 via fink, lasair\n"
        )
    ).workflow
    confirm = next(step for step in workflow.steps if isinstance(step, ConfirmStep))

    result = validate_step_capabilities(confirm, graph)

    assert result.status == "supported"
    assert {item.source.broker for item in result.source_results} == {"fink", "lasair"}
    assert all(item.candidates for item in result.source_results)
    assert {
        (candidate.broker, candidate.endpoint)
        for candidate in result.candidates
    } == {("fink", "objects"), ("lasair", "objects")}


def test_surface_capability_validation_uses_the_adjacent_proposition_too():
    graph = build_capability_graph()
    surface = parse_surface_script(
        "objects from ztf via alerce\n"
        'where classification.best.class = "SN"\n'
        "confirm by 2 via fink, lasair\n"
    )

    report = validate_surface_capabilities(surface, graph=graph)
    checks = [check for check in report.checks if check.subject == "confirm"]

    assert len(checks) == 2
    assert all(check.status is SurfaceCapabilityStatus.SUPPORTED for check in checks)
    assert {
        (check.broker, check.evidence[0].endpoints)
        for check in checks
    } == {("fink", ("objects",)), ("lasair", ("objects",))}


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


def test_singular_confirm_endpoint_uses_generic_runtime_fanout():
    graph = build_capability_graph()
    workflow = compile_surface_to_ir(
        parse_surface_script(
            "objects from ztf via alerce\n"
            "inside (124.87996115142856, -6.0205001, 5arcsec)\n"
            "confirm by 1 via antares\n"
        ),
        graph=graph,
    )

    run = plan_workflow(workflow, graph)

    assert [plan.endpoint for plan in run.steps[1].endpoint_plans] == [
        "get_by_ztf_object_id"
    ]
    assert run.steps[1].endpoint_plans[0].candidate_input_from == CandidateInputRef(
        step_index=0
    )
