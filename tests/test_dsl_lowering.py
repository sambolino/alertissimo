from datetime import timedelta

import pytest

from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraph,
    EndpointCapability,
    SemanticRecordCapability,
)
from alertissimo.dsl import (
    SurfaceLoweringError,
    compile_surface,
    compile_surface_to_ir,
    lower_surface,
    lower_surface_to_ir,
    parse_surface_script,
)
from alertissimo.orchestration.ir import (
    BooleanPredicate,
    ClassifyStep,
    ColorMagnitudeStep,
    ComparisonPredicate,
    ConeSearchStep,
    FilterStep,
    GetClassificationStep,
    GetCrossmatchStep,
    LookupStep,
    MatchStep,
    PredicateLiteral,
    SearchSelection,
    SemanticReference,
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
            "classification@dsl.best.class",
            "classification@dsl.best.probability",
        }


def _endpoint(
    broker: str,
    origin: str,
    endpoint: str,
    *operations: str,
    params: tuple[str, ...] = (),
    server_filters: tuple[str, ...] = (),
    binding_roles: tuple[str, ...] = (),
    collection_binding_roles: tuple[str, ...] = (),
) -> EndpointCapability:
    return EndpointCapability(
        broker=broker,
        origin=origin,
        endpoint=endpoint,
        path=f"/{endpoint}",
        method="GET",
        operation_types=tuple(operations),
        params=params,
        server_filters=server_filters,
        projection_param=None,
        supports_projection=False,
        output_type="array",
        binding_roles=binding_roles,
        collection_binding_roles=collection_binding_roles,
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


def test_explicit_identifier_population_lowers_to_typed_lookup_step():
    workflow = lower_surface_to_ir(
        parse_surface_script(
            "objects ZTF20abc, ZTF21def from ztf via lasair\n"
            "with lightcurve via fink\n"
        ),
        semantic_paths=_FakeSemanticPaths(),
    )

    lookup = workflow.steps[0]
    assert isinstance(lookup, LookupStep)
    assert lookup.target.ids == ["ZTF20abc", "ZTF21def"]
    assert lookup.target.kind == "object"
    assert [(source.broker, source.origin) for source in lookup.sources] == [
        ("lasair", "ztf")
    ]


def test_alert_spelling_lowers_to_alert_lookup_before_capability_planning():
    workflow = lower_surface_to_ir(
        parse_surface_script("alert 123456 from ztf via fink\n"),
        semantic_paths=_FakeSemanticPaths(),
    )
    lookup = workflow.steps[0]
    assert isinstance(lookup, LookupStep)
    assert lookup.target.ids == ["123456"]
    assert lookup.target.kind == "alert"


def _dynamic_crossmatch_graph() -> CapabilityGraph:
    endpoints = (
        _endpoint("lasair", "ztf", "cone", "cone_search"),
        _endpoint("lasair", "ztf", "object", "object_lookup"),
    )
    records = (
        _record("lasair", "ztf", "summary@ztf:lasair", "cone", "object"),
        _record("lasair", "ztf", "crossmatch@{producer}:lasair", "object"),
    )
    return CapabilityGraph(endpoints, (), (), (), records)


def _alerce_graph() -> CapabilityGraph:
    endpoints = (
        _endpoint(
            "alerce",
            "lsst",
            "query_objects",
            "object_search",
            "classification_filter",
            params=("classifier", "class_name", "probability"),
            server_filters=("classifier", "class_name", "probability"),
        ),
    )
    records = (
        _record("alerce", "lsst", "summary@lsst:alerce", "query_objects"),
        _record(
            "alerce",
            "lsst",
            "classification@{producer}:alerce",
            "query_objects",
        ),
    )
    return CapabilityGraph(endpoints, (), (), (), records)


def _lower(script: str):
    return lower_surface(
        parse_surface_script(script),
        semantic_paths=_FakeSemanticPaths(),
    )


def _assert_reference_literal(
    predicate,
    *,
    semantic_type: str,
    field_path: str,
    operator: str,
    value,
    producer: str | None = None,
    channel: str | None = None,
):
    assert isinstance(predicate, ComparisonPredicate)
    assert predicate.operator == operator
    assert predicate.left == SemanticReference(
        semantic_type=semantic_type,
        field_path=field_path,
        producer=producer,
        channel=channel,
    )
    assert predicate.right == PredicateLiteral(value=value)


def test_latest_is_search_selection_not_ir_step():
    compilation = _lower(
        """objects from lsst, ztf via fink
within 7d
latest 100
"""
    )

    assert len(compilation.workflow.steps) == 1
    search = compilation.workflow.steps[0]
    assert isinstance(search, SemanticSearchStep)
    assert [(source.origin, source.broker) for source in search.sources] == [
        ("lsst", "fink"),
        ("ztf", "fink"),
    ]
    assert search.time_context.window == timedelta(days=7)
    assert search.time_context.relative_to == "now"
    assert search.selection == SearchSelection(latest=100)


def test_inside_lowers_to_summary_cone_search_with_selection_and_radius_conversion():
    compilation = _lower(
        """objects from lsst via fink
latest 25
inside (34, 33, 0.5deg)
"""
    )

    step = compilation.workflow.steps[0]
    assert isinstance(step, ConeSearchStep)
    assert step.semantic_type == "summary"
    assert step.radius == 1800.0
    assert step.selection.latest == 25
    assert step.sources[0].origin == "lsst"
    assert step.sources[0].broker == "fink"


def test_inside_without_unit_is_rejected_instead_of_guessing():
    with pytest.raises(SurfaceLoweringError) as exc:
        _lower("objects from lsst\ninside (34, 33, 0.5)\n")

    assert exc.value.code == "ambiguous_angle_unit"


def test_order_by_lowers_only_to_result_view_not_workflow_step():
    compilation = _lower(
        "objects from lsst\norder by summary.time.last_mjd desc\n"
    )

    assert len(compilation.workflow.steps) == 1
    assert isinstance(compilation.workflow.steps[0], SemanticSearchStep)
    assert compilation.view.order_by.expression == "summary.time.last_mjd"
    assert compilation.view.order_by.direction == "desc"


def test_workflow_only_compatibility_helper_refuses_to_drop_result_view():
    surface = parse_surface_script(
        "objects from lsst\norder by summary.time.last_mjd desc\n"
    )

    with pytest.raises(SurfaceLoweringError) as exc:
        lower_surface_to_ir(surface, semantic_paths=_FakeSemanticPaths())

    assert exc.value.code == "result_view_present"


def test_general_where_is_candidate_search_predicate_not_filter_step():
    compilation = _lower(
        "objects from lsst\nwhere summary.time.last_mjd > 60000\n"
    )

    assert len(compilation.workflow.steps) == 1
    search = compilation.workflow.steps[0]
    assert isinstance(search, SemanticSearchStep)
    assert search.criteria == {}
    _assert_reference_literal(
        search.predicate,
        semantic_type="summary",
        field_path="time.last_mjd",
        operator=">",
        value=60000,
    )


def test_scoped_classification_predicate_implies_search_condition_and_requirement():
    compilation = _lower(
        "objects from lsst via alerce\n"
        'with classification from lc_classifier where best.class = "SN" AND '
        "best.probability >= 0.8\n"
    )

    assert [type(step) for step in compilation.workflow.steps] == [
        SemanticSearchStep,
        GetClassificationStep,
    ]
    search = compilation.workflow.steps[0]
    assert search.criteria == {}
    assert isinstance(search.predicate, BooleanPredicate)
    assert search.predicate.operator == "and"
    _assert_reference_literal(
        search.predicate.operands[0],
        semantic_type="classification",
        field_path="best.class",
        operator="=",
        value="SN",
        producer="lc_classifier",
        channel="alerce",
    )
    _assert_reference_literal(
        search.predicate.operands[1],
        semantic_type="classification",
        field_path="best.probability",
        operator=">=",
        value=0.8,
        producer="lc_classifier",
        channel="alerce",
    )
    classification = compilation.workflow.steps[1]
    assert classification.classifier == "lc_classifier"
    assert [(source.origin, source.broker) for source in classification.sources] == [
        ("lsst", "alerce")
    ]


def test_inline_with_where_has_scoped_search_semantics():
    compilation = _lower(
        "objects from lsst via alerce\n"
        'with classification from lc_classifier where best.class = "LPV" AND '
        "best.probability >= 0.8\n"
    )

    search = compilation.workflow.steps[0]
    assert isinstance(search.predicate, BooleanPredicate)
    _assert_reference_literal(
        search.predicate.operands[0],
        semantic_type="classification",
        field_path="best.class",
        operator="=",
        value="LPV",
        producer="lc_classifier",
        channel="alerce",
    )
    assert compilation.workflow.steps[1].classifier == "lc_classifier"


def test_fully_qualified_general_where_implies_classification_requirement():
    compilation = _lower(
        "objects from lsst via alerce\n"
        'where classification@lc_classifier.best.class = "SN" and '
        "classification@lc_classifier.best.probability >= 0.8\n"
    )

    assert [type(step) for step in compilation.workflow.steps] == [
        SemanticSearchStep,
        GetClassificationStep,
    ]
    search = compilation.workflow.steps[0]
    assert isinstance(search.predicate, BooleanPredicate)
    _assert_reference_literal(
        search.predicate.operands[0],
        semantic_type="classification",
        field_path="best.class",
        operator="=",
        value="SN",
        producer="lc_classifier",
    )
    assert compilation.workflow.steps[1].classifier == "lc_classifier"


def test_explicit_with_deduplicates_requirement_implied_by_general_where():
    compilation = _lower(
        "objects from lsst via alerce\n"
        'where classification@lc_classifier.best.class = "SN"\n'
        "with classification from lc_classifier\n"
    )

    assert sum(
        isinstance(step, GetClassificationStep)
        for step in compilation.workflow.steps
    ) == 1


def test_second_pass_scoped_with_enriches_then_filters_current_candidates():
    compilation = _lower(
        "objects from lsst via alerce\n"
        "filter summary.time.last_mjd > 60000\n"
        'with classification from lc_classifier where best.class = "SN" AND '
        "best.probability >= 0.8\n"
    )

    assert [type(step) for step in compilation.workflow.steps] == [
        SemanticSearchStep,
        FilterStep,
        GetClassificationStep,
        FilterStep,
    ]
    first_filter = compilation.workflow.steps[1]
    _assert_reference_literal(
        first_filter.predicate,
        semantic_type="summary",
        field_path="time.last_mjd",
        operator=">",
        value=60000,
    )
    scoped_filter = compilation.workflow.steps[-1]
    assert isinstance(scoped_filter.predicate, BooleanPredicate)
    _assert_reference_literal(
        scoped_filter.predicate.operands[0],
        semantic_type="classification",
        field_path="best.class",
        operator="=",
        value="SN",
        producer="lc_classifier",
        channel="alerce",
    )


def test_with_crossmatch_preserves_fixed_origin_and_local_broker_override():
    compilation = _lower(
        "objects from lsst via fink\n"
        "with crossmatch from gaia via antares\n"
    )

    step = compilation.workflow.steps[1]
    assert isinstance(step, GetCrossmatchStep)
    assert step.catalog == "gaia"
    assert [(source.origin, source.broker) for source in step.sources] == [
        ("lsst", "antares")
    ]


def test_classification_using_method_lowers_to_local_classify():
    compilation = _lower(
        "objects from ztf via antares\n"
        "with classification using alertissimo:clasMeV2\n"
    )

    step = compilation.workflow.steps[1]
    assert isinstance(step, ClassifyStep)
    assert step.method == "alertissimo:clasMeV2"
    assert step.sources == []


def test_color_magnitude_requirement_lowers_to_local_derivation():
    compilation = _lower(
        "objects from lsst\nwith color-magnitude g-r vs r\n"
    )

    step = compilation.workflow.steps[1]
    assert isinstance(step, ColorMagnitudeStep)
    assert step.color == "g-r"
    assert step.magnitude_field == "r"


def test_match_between_candidate_origins_keeps_candidates_as_working_context():
    compilation = _lower(
        "objects from lsst, ztf\nmatch on position within 1arcsec\n"
    )

    step = compilation.workflow.steps[1]
    assert isinstance(step, MatchStep)
    assert step.sources == []
    assert step.params == {
        "candidate_origins": ["lsst", "ztf"],
        "predicate": "position within 1arcsec",
    }


def test_external_match_uses_counterpart_source_without_mutating_candidates():
    compilation = _lower(
        "objects from lsst via fink\n"
        "match from icecube within 3d on position within 2deg\n"
    )

    step = compilation.workflow.steps[1]
    assert isinstance(step, MatchStep)
    assert step.params["candidate_origins"] == ["lsst"]
    assert step.params["counterpart_origin"] == "icecube"
    assert step.params["max_time_delta"] == timedelta(days=3)
    assert step.params["predicate"] == "position within 2deg"
    assert [(source.origin, source.broker) for source in step.sources] == [
        ("icecube", "fink")
    ]


def test_ranked_by_remains_unlowered_until_ranking_semantics_exist():
    with pytest.raises(SurfaceLoweringError) as exc:
        _lower("objects from lsst\nranked by followup utility\n")

    assert exc.value.code == "ranking_semantics_deferred"


def test_search_selection_classifier_and_predicate_round_trip_through_workflow_union():
    workflow = WorkflowIR(
        steps=[
            SemanticSearchStep(
                semantic_type="summary",
                selection=SearchSelection(latest=5),
                predicate=ComparisonPredicate(
                    operator=">",
                    left=SemanticReference(
                        semantic_type="summary", field_path="time.last_mjd"
                    ),
                    right=PredicateLiteral(value=60000),
                ),
            ),
            GetClassificationStep(classifier="lc_classifier"),
        ]
    )

    restored = WorkflowIR.model_validate(workflow.model_dump())
    assert restored == workflow
    assert restored.steps[0].selection.latest == 5
    assert restored.steps[0].predicate == workflow.steps[0].predicate
    assert restored.steps[1].classifier == "lc_classifier"


def test_compile_supports_alerce_dynamic_classifier_when_selector_is_registered():
    surface = parse_surface_script(
        "objects from lsst via alerce\n"
        'with classification from lc_classifier where best.class = "SN" AND '
        "best.probability >= 0.8\n"
    )

    compilation = compile_surface(
        surface,
        graph=_alerce_graph(),
        semantic_paths=_FakeSemanticPaths(),
    )

    assert isinstance(compilation.workflow.steps[0], SemanticSearchStep)
    assert isinstance(compilation.workflow.steps[1], GetClassificationStep)
    assert compilation.workflow.steps[1].classifier == "lc_classifier"


def test_compile_runs_capabilities_before_lowering_exact_crossmatch_requirement():
    surface = parse_surface_script(
        "objects from ztf via antares\n"
        "inside (34, 33, 0.5deg)\n"
        "with crossmatch from gaia\n"
    )

    compilation = compile_surface(
        surface,
        graph=_supported_graph(),
        semantic_paths=_FakeSemanticPaths(),
    )

    assert isinstance(compilation.workflow.steps[0], ConeSearchStep)
    assert isinstance(compilation.workflow.steps[1], GetCrossmatchStep)
    assert compilation.workflow.steps[1].catalog == "gaia"


def test_compile_refuses_dynamic_crossmatch_capability_that_is_only_deferred():
    surface = parse_surface_script(
        "objects from ztf via lasair\n"
        "inside (34, 33, 0.5deg)\n"
        "with crossmatch from gaia\n"
    )

    with pytest.raises(SurfaceLoweringError) as exc:
        compile_surface(
            surface,
            graph=_dynamic_crossmatch_graph(),
            semantic_paths=_FakeSemanticPaths(),
        )

    assert exc.value.code == "deferred_capability"


def test_compile_surface_to_ir_refuses_to_discard_order_view():
    surface = parse_surface_script(
        "objects from lsst\norder by summary.time.last_mjd desc\n"
    )

    with pytest.raises(SurfaceLoweringError) as exc:
        compile_surface_to_ir(
            surface,
            graph=CapabilityGraph((), (), (), (), ()),
            semantic_paths=_FakeSemanticPaths(),
        )

    assert exc.value.code == "unsupported_capability"
