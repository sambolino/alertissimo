import pytest

from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import (
    DSLParseError,
    FilterClause,
    RequirementClause,
    SurfaceFragment,
    compile_surface,
    compile_surface_fragment,
    parse_surface_fragment,
    parse_surface_script,
    validate_surface_fragment_capabilities,
    validate_surface_fragment_semantics,
)


BASE_SOURCE = """objects from ztf via lasair
inside (124.87996115142856, -6.0205001, 5arcsec)
with lightcurve via fink
"""


def _base_workflow():
    return compile_surface(
        parse_surface_script(BASE_SOURCE),
        graph=build_capability_graph(),
    ).workflow


def test_fragment_parser_produces_clause_only_surface_without_candidates():
    fragment = parse_surface_fragment(
        """filter detection@ztf:fink.quality.real_bogus >= 0.8
with lightcurve via lasair
"""
    )

    assert isinstance(fragment, SurfaceFragment)
    assert [type(clause) for clause in fragment.clauses] == [
        FilterClause,
        RequirementClause,
    ]
    assert not hasattr(fragment, "candidates")


@pytest.mark.parametrize(
    "source",
    [
        "objects from ztf via alerce",
        "inside (1, 2, 3arcsec)",
        "within 2d",
        "latest 10",
        "where summary@ztf:lasair.identity.object_id exists",
    ],
)
def test_fragment_parser_rejects_initial_candidate_intent(source):
    with pytest.raises(DSLParseError):
        parse_surface_fragment(source)


def test_fragment_compilation_extends_ir_exactly_without_reconstructing_dsl():
    base = _base_workflow()
    fragment = parse_surface_fragment(
        """filter detection@ztf:fink.quality.real_bogus >= 0.8
with lightcurve via lasair
"""
    )

    compilation = compile_surface_fragment(
        fragment,
        base,
        graph=build_capability_graph(),
    )

    assert compilation.workflow is not base
    assert compilation.workflow.steps[: len(base.steps)] == base.steps
    assert [step.op for step in base.steps] == ["cone_search", "get_lightcurve"]
    assert [step.op for step in compilation.workflow.steps] == [
        "cone_search",
        "get_lightcurve",
        "filter",
        "get_lightcurve",
    ]


def test_scoped_with_predicate_becomes_post_materialization_filter_in_fragment():
    base = _base_workflow()
    fragment = parse_surface_fragment(
        "with classification via alerce where best.probability >= 0.5"
    )

    compilation = compile_surface_fragment(
        fragment,
        base,
        graph=build_capability_graph(),
    )

    assert compilation.workflow.steps[: len(base.steps)] == base.steps
    assert [step.op for step in compilation.workflow.steps[-2:]] == [
        "get_classification",
        "filter",
    ]


def test_fragment_validation_uses_ir_candidate_context_but_reports_only_new_work():
    base = _base_workflow()
    fragment = parse_surface_fragment("with lightcurve via lasair")

    semantic = validate_surface_fragment_semantics(fragment, base)
    capabilities = validate_surface_fragment_capabilities(
        fragment,
        base,
        graph=build_capability_graph(),
    )

    assert semantic.is_valid
    assert capabilities.checks
    assert all(check.subject != "candidates" for check in capabilities.checks)
    assert {check.subject for check in capabilities.checks} == {"requirement"}
