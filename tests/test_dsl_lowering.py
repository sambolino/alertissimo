from datetime import timedelta

import pytest

from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraph,
    EndpointCapability,
    SemanticRecordCapability,
)
from alertissimo.dsl import (
    SurfaceLoweringError,
    compile_surface_to_ir,
    lower_surface_to_ir,
    parse_surface_script,
)
from alertissimo.orchestration.ir import (
    ClassifyStep,
    ColorMagnitudeStep,
    ConeSearchStep,
    FilterStep,
    GetClassificationStep,
    GetCrossmatchStep,
    LatestStep,
    MatchStep,
    OrderStep,
    SemanticSearchStep,
    WorkflowIR,
)


class _FakeSemanticPaths:
    record_types = frozenset(
        {
            "summary",
            "detection",
            "lightcurve",
            "crossmatch",
            "classification",
            "color_magnitude",
            "color_color",
            "spectrum",
            "data_product",
        }
    )

    def is_valid(self, semantic_path: str) -> bool:
        return semantic_path in {
            "summary@dsl.time.last_mjd",
            "classification@dsl.best.probability",
        }


def _endpoint(
    broker: str,
    origin: str,
    endpoint: str,
    *operations: str,
) -> EndpointCapability:
    return EndpointCapability(
        broker=broker,
        origin=origin,
        endpoint=endpoint,
        path=f"/{endpoint}",
        method="GET",
        operation_types=tuple(operations),
        params=(),
        server_filters=(),
        projection_param=None,
        supports_projection=False,
        output_type="array",
    )


def _record(
    broker: str,
    origin: str,
    semantic_record_type: str,
    *endpoints: str,
) -> SemanticRecordCapability:
    return SemanticRecordCapability(
        broker=broker,
        origin=origin,
        semantic_record_type=semantic_record_type,
        endpoints=tuple(endpoints),
        fields=(),
    )


def _supported_graph() -> CapabilityGraph:
    endpoints = (
        _endpoint("antares", "ztf", "cone", "spatial_search"),
        _endpoint("antares", "ztf", "object", "object_lookup"),
    )
    records = (
        _record("antares", "ztf", "summary@ztf:antares", "cone", "object"),
        _record("antares", "ztf", "crossmatch@gaia:antares", "object"),
    )
    return CapabilityGraph(endpoints, (), (), (), records)


def _dynamic_graph() -> CapabilityGraph:
    endpoints = (
        _endpoint("lasair", "ztf", "cone", "cone_search"),
        _endpoint("lasair", "ztf", "object", "object_lookup"),
    )
    records = (
        _record("lasair", "ztf", "summary@ztf:lasair", "cone", "object"),
        _record("lasair", "ztf", "crossmatch@{producer}:lasair", "object"),
    )
    return CapabilityGraph(endpoints, (), (), (), records)


def _lower(script: str) -> WorkflowIR:
    return lower_surface_to_ir(
        parse_surface_script(script),
        semantic_paths=_FakeSemanticPaths(),
    )


def test_candidate_header_time_latest_and_order_lower_without_provider_details():
    workflow = _lower(
        """
        objects from lsst, ztf via fink
        within 7d
        latest 100
        order by summary.time.last_mjd desc
        """
    )

    assert [type(step) for step in workflow.steps] == [
        SemanticSearchStep,
        LatestStep,
        OrderStep,
    ]
    search = workflow.steps[0]
    assert [(source.origin, source.broker) for source in search.sources] == [
        ("lsst", "fink"),
        ("ztf", "fink"),
    ]
    assert search.time_context.window == timedelta(days=7)
    assert search.time_context.relative_to == "now"
    assert workflow.steps[1].count == 100
    assert workflow.steps[2].expression == "summary.time.last_mjd"
    assert workflow.steps[2].direction == "desc"


def test_inside_lowers_to_summary_cone_search_and_converts_radius_to_arcsec():
    workflow = _lower(
        "objects from lsst via fink\n"
        "inside (34, 33, 0.5deg)\n"
    )

    step = workflow.steps[0]
    assert isinstance(step, ConeSearchStep)
    assert step.semantic_type == "summary"
    assert step.radius == 1800.0
    assert step.sources[0].origin == "lsst"
    assert step.sources[0].broker == "fink"


def test_inside_without_unit_is_rejected_instead_of_guessing():
    with pytest.raises(SurfaceLoweringError) as exc:
        _lower("objects from lsst\ninside (34, 33, 0.5)\n")

    assert exc.value.code == "ambiguous_angle_unit"


def test_where_and_filter_are_internal_filters_in_declared_order():
    workflow = _lower(
        """
        objects from lsst
        where classification = "SN Ia"
        with classification
        filter classification.best.probability > 0.8
        """
    )

    assert [type(step) for step in workflow.steps] == [
        SemanticSearchStep,
        FilterStep,
        GetClassificationStep,
        FilterStep,
    ]
    assert workflow.steps[1].criteria == {
        "expression": 'classification = "SN Ia"'
    }
    assert workflow.steps[3].criteria == {
        "expression": "classification.best.probability > 0.8"
    }


def test_with_crossmatch_preserves_fixed_origin_and_local_broker_override():
    workflow = _lower(
        "objects from lsst via fink\n"
        "with crossmatch from gaia via antares\n"
    )

    step = workflow.steps[1]
    assert isinstance(step, GetCrossmatchStep)
    assert step.catalog == "gaia"
    assert [(source.origin, source.broker) for source in step.sources] == [
        ("lsst", "antares")
    ]


def test_classification_using_method_lowers_to_local_classify():
    workflow = _lower(
        "objects from ztf via antares\n"
        "with classification using alertissimo:clasMeV2\n"
    )

    step = workflow.steps[1]
    assert isinstance(step, ClassifyStep)
    assert step.method == "alertissimo:clasMeV2"
    assert step.sources == []


def test_common_classification_producer_equal_to_broker_is_lossless():
    workflow = _lower(
        "objects from lsst via fink\n"
        "with classification from fink\n"
    )

    step = workflow.steps[1]
    assert isinstance(step, GetClassificationStep)
    assert [(source.origin, source.broker) for source in step.sources] == [
        ("lsst", "fink")
    ]


def test_rare_cross_channel_classification_producer_remains_explicitly_deferred():
    with pytest.raises(SurfaceLoweringError) as exc:
        _lower(
            "objects from lsst via fink\n"
            "with classification from fink via ampel\n"
        )

    assert exc.value.code == "unrepresentable_classification_producer"


def test_color_magnitude_requirement_lowers_to_local_derivation():
    workflow = _lower(
        "objects from lsst\n"
        "with color-magnitude g-r vs r\n"
    )

    step = workflow.steps[1]
    assert isinstance(step, ColorMagnitudeStep)
    assert step.color == "g-r"
    assert step.magnitude_field == "r"


def test_match_between_candidate_origins_keeps_candidates_as_working_context():
    workflow = _lower(
        "objects from lsst, ztf\n"
        "match on position within 1arcsec\n"
    )

    step = workflow.steps[1]
    assert isinstance(step, MatchStep)
    assert step.sources == []
    assert step.params == {
        "candidate_origins": ["lsst", "ztf"],
        "predicate": "position within 1arcsec",
    }


def test_external_match_uses_counterpart_source_without_mutating_candidates():
    workflow = _lower(
        "objects from lsst via fink\n"
        "match from icecube within 3d on position within 2deg\n"
    )

    step = workflow.steps[1]
    assert isinstance(step, MatchStep)
    assert step.params["candidate_origins"] == ["lsst"]
    assert step.params["counterpart_origin"] == "icecube"
    assert step.params["max_time_delta"] == timedelta(days=3)
    assert step.params["predicate"] == "position within 2deg"
    assert [(source.origin, source.broker) for source in step.sources] == [
        ("icecube", "fink")
    ]


def test_candidate_scope_constraints_cannot_appear_after_operations():
    with pytest.raises(SurfaceLoweringError) as exc:
        _lower(
            "objects from lsst\n"
            "latest 10\n"
            "within 7d\n"
        )

    assert exc.value.code == "late_candidate_constraint"


def test_ranked_by_remains_unlowered_until_ranking_semantics_exist():
    with pytest.raises(SurfaceLoweringError) as exc:
        _lower(
            "objects from lsst\n"
            "ranked by followup utility\n"
        )

    assert exc.value.code == "ranking_semantics_deferred"


def test_new_local_selection_steps_round_trip_through_workflow_union():
    workflow = WorkflowIR(
        steps=[
            LatestStep(count=5),
            OrderStep(expression="summary.time.last_mjd", direction="desc"),
        ]
    )

    restored = WorkflowIR.model_validate(workflow.model_dump())
    assert restored == workflow
    assert isinstance(restored.steps[0], LatestStep)
    assert isinstance(restored.steps[1], OrderStep)


def test_compile_runs_capabilities_before_lowering_exact_provider_requirement():
    surface = parse_surface_script(
        "objects from ztf via antares\n"
        "inside (34, 33, 0.5deg)\n"
        "with crossmatch from gaia\n"
    )

    workflow = compile_surface_to_ir(
        surface,
        graph=_supported_graph(),
        semantic_paths=_FakeSemanticPaths(),
    )

    assert isinstance(workflow.steps[0], ConeSearchStep)
    assert isinstance(workflow.steps[1], GetCrossmatchStep)
    assert workflow.steps[1].catalog == "gaia"


def test_compile_refuses_dynamic_provider_capability_that_is_only_deferred():
    surface = parse_surface_script(
        "objects from ztf via lasair\n"
        "inside (34, 33, 0.5deg)\n"
        "with crossmatch from gaia\n"
    )

    with pytest.raises(SurfaceLoweringError) as exc:
        compile_surface_to_ir(
            surface,
            graph=_dynamic_graph(),
            semantic_paths=_FakeSemanticPaths(),
        )

    assert exc.value.code == "deferred_capability"
