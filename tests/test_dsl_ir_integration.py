from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import (
    compile_surface_to_ir, lower_surface, parse_surface_script, validate_surface_capabilities,
)
from alertissimo.orchestration.ir import ConeSearchStep, SearchSelection, SemanticSearchStep
from alertissimo.orchestration.validation import validate_step_capabilities


class _FakeSemanticPaths:
    record_types = frozenset({"summary"})

    def is_valid(self, semantic_path: str) -> bool:
        return True


def test_lowered_fink_lsst_inside_uses_registered_spatial_search_operation():
    compilation = lower_surface(
        parse_surface_script(
            "objects from lsst via fink\n"
            "inside (34, 33, 0.5deg)\n"
        ),
        semantic_paths=_FakeSemanticPaths(),
    )

    step = compilation.workflow.steps[0]
    assert isinstance(step, ConeSearchStep)
    result = validate_step_capabilities(step, build_capability_graph())

    assert result.status == "supported"
    assert {candidate.endpoint for candidate in result.candidates} == {"conesearch"}


def test_latest_remains_search_selection_under_provider_capability_validation():
    compilation = lower_surface(
        parse_surface_script(
            "objects from lsst via alerce\n"
            "latest 10\n"
        ),
        semantic_paths=_FakeSemanticPaths(),
    )

    step = compilation.workflow.steps[0]
    assert isinstance(step, SemanticSearchStep)
    assert step.selection == SearchSelection(latest=10)
    result = validate_step_capabilities(step, build_capability_graph())
    assert result.status == "deferred"
    assert "latest requires" in result.source_results[0].reason


def test_order_by_is_result_view_and_never_workflow_ir():
    compilation = lower_surface(
        parse_surface_script(
            "objects from lsst via alerce\n"
            "order by summary.time.last_mjd desc\n"
        ),
        semantic_paths=_FakeSemanticPaths(),
    )

    assert len(compilation.workflow.steps) == 1
    assert isinstance(compilation.workflow.steps[0], SemanticSearchStep)
    assert compilation.view.order_by.expression == "summary.time.last_mjd"
    assert compilation.view.order_by.direction == "desc"


def test_public_dsl_validation_reports_latest_deferral_and_preserves_supported_case():
    graph = build_capability_graph()
    for origin, status in (("ztf", "supported"), ("lsst", "deferred")):
        report = validate_surface_capabilities(parse_surface_script(f"objects from {origin} via alerce\nlatest 1\n"), graph=graph)
        check, = (item for item in report.checks if item.subject == "selection")
        assert check.status.value == status
    workflow = compile_surface_to_ir(parse_surface_script("objects from ztf via alerce\nlatest 1\n"), graph=graph)
    assert workflow.steps[0].selection.latest == 1
