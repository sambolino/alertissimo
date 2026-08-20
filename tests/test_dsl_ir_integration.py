from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import lower_surface_to_ir, parse_surface_script
from alertissimo.orchestration.ir import LatestStep, OrderStep
from alertissimo.orchestration.validation import validate_step_capabilities


class _FakeSemanticPaths:
    record_types = frozenset({"summary"})

    def is_valid(self, semantic_path: str) -> bool:
        return True


def test_lowered_fink_lsst_inside_uses_registered_spatial_search_operation():
    workflow = lower_surface_to_ir(
        parse_surface_script(
            "objects from lsst via fink\n"
            "inside (34, 33, 0.5deg)\n"
        ),
        semantic_paths=_FakeSemanticPaths(),
    )

    result = validate_step_capabilities(workflow.steps[0], build_capability_graph())

    assert result.status == "supported"
    assert {candidate.endpoint for candidate in result.candidates} == {"conesearch"}


def test_order_and_latest_are_local_to_provider_capability_validation():
    graph = build_capability_graph()

    assert validate_step_capabilities(
        LatestStep(count=10), graph
    ).status == "not_applicable"
    assert validate_step_capabilities(
        OrderStep(expression="summary.time.last_mjd", direction="desc"), graph
    ).status == "not_applicable"
