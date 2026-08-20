from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraph,
    EndpointCapability,
    build_capability_graph,
)
from alertissimo.data_layer.runtime.predicate_bindings import (
    PredicateBindingCapability,
    PredicateBindingRegistry,
    build_predicate_binding_registry,
)
from alertissimo.dsl import bind_surface_predicates, parse_surface_script


class _SemanticPaths:
    record_types = frozenset({"summary", "classification", "crossmatch"})


def _endpoint(broker: str, origin: str, endpoint: str) -> EndpointCapability:
    return EndpointCapability(
        broker=broker,
        origin=origin,
        endpoint=endpoint,
        path=f"/{endpoint}",
        method="GET",
        operation_types=("object_search",),
        params=("classifier", "class_name", "probability"),
        server_filters=("classifier", "class_name", "probability"),
        projection_param=None,
        supports_projection=False,
        output_type="array",
    )


def _generic_registry() -> PredicateBindingRegistry:
    return PredicateBindingRegistry(
        (
            PredicateBindingCapability(
                broker="demo",
                origin="lsst",
                endpoint="objects",
                physical_param="classifier",
                semantic_record="classification",
                semantic_path=None,
                value_from="producer",
            ),
            PredicateBindingCapability(
                broker="demo",
                origin="lsst",
                endpoint="objects",
                physical_param="class_name",
                semantic_record="classification",
                semantic_path="classification.best.class",
                value_from="literal",
                operators=("=",),
                requires_producer=True,
            ),
            PredicateBindingCapability(
                broker="demo",
                origin="lsst",
                endpoint="objects",
                physical_param="probability",
                semantic_record="classification",
                semantic_path="classification.best.probability",
                value_from="literal",
                operators=(">=",),
                requires_producer=True,
            ),
        )
    )


def _generic_graph() -> CapabilityGraph:
    return CapabilityGraph(
        endpoint_capabilities=(_endpoint("demo", "lsst", "objects"),),
        payload_capabilities=(),
        field_mapping_capabilities=(),
        transform_capabilities=(),
        semantic_record_capabilities=(),
    )


def test_real_registry_declares_alerce_lsst_query_objects_bindings():
    graph = build_capability_graph()
    registry = build_predicate_binding_registry(graph)

    bindings = registry.query(
        broker="alerce", origin="lsst", endpoint="query_objects"
    )

    assert {
        (
            item.physical_param,
            item.semantic_path,
            item.value_from,
            item.operators,
            item.requires_producer,
        )
        for item in bindings
    } == {
        ("classifier", None, "producer", (), False),
        ("class_name", "classification.best.class", "literal", ("=",), True),
        (
            "probability",
            "classification.best.probability",
            "literal",
            (">=",),
            True,
        ),
    }


def test_scoped_alerce_classification_predicate_binds_exact_query_objects_params():
    graph = build_capability_graph()
    surface = parse_surface_script(
        """objects from lsst via alerce
with classification from lc_classifier:
    best.class = "SN"
    best.probability >= 0.8
"""
    )

    report = bind_surface_predicates(surface, graph)

    assert len(report.complete_endpoints) == 1
    binding = report.complete_endpoints[0]
    assert (binding.broker, binding.origin, binding.endpoint) == (
        "alerce",
        "lsst",
        "query_objects",
    )
    assert binding.params == {
        "class_name": "SN",
        "classifier": "lc_classifier",
        "probability": 0.8,
    }
    assert binding.total_predicates == 2
    assert binding.residual_reasons == ()


def test_fully_qualified_general_where_binds_same_alerce_params():
    graph = build_capability_graph()
    surface = parse_surface_script(
        "objects from lsst via alerce\n"
        'where classification@lc_classifier.best.class = "SN" and '
        "classification@lc_classifier.best.probability >= 0.8\n"
    )

    report = bind_surface_predicates(surface, graph)

    assert len(report.complete_endpoints) == 1
    assert report.complete_endpoints[0].params == {
        "class_name": "SN",
        "classifier": "lc_classifier",
        "probability": 0.8,
    }


def test_generic_registry_proves_binder_has_no_alerce_hardcode():
    surface = parse_surface_script(
        """objects from lsst via demo
with classification from lc_classifier:
    best.class = "SN"
    best.probability >= 0.8
"""
    )

    report = bind_surface_predicates(
        surface,
        _generic_graph(),
        predicate_registry=_generic_registry(),
        semantic_paths=_SemanticPaths(),
    )

    assert len(report.complete_endpoints) == 1
    binding = report.complete_endpoints[0]
    assert binding.endpoint == "objects"
    assert binding.params == {
        "class_name": "SN",
        "classifier": "lc_classifier",
        "probability": 0.8,
    }


def test_probability_less_than_is_not_misrepresented_as_minimum_threshold():
    surface = parse_surface_script(
        """objects from lsst via demo
with classification from lc_classifier:
    best.probability < 0.8
"""
    )

    report = bind_surface_predicates(
        surface,
        _generic_graph(),
        predicate_registry=_generic_registry(),
        semantic_paths=_SemanticPaths(),
    )

    binding = report.endpoints[0]
    assert not binding.complete
    assert binding.params == {}
    assert "no exact declared binding" in binding.residual_reasons[0]


def test_classification_field_without_explicit_producer_does_not_use_provider_default():
    surface = parse_surface_script(
        """objects from lsst via demo
with classification:
    best.class = "SN"
"""
    )

    report = bind_surface_predicates(
        surface,
        _generic_graph(),
        predicate_registry=_generic_registry(),
        semantic_paths=_SemanticPaths(),
    )

    binding = report.endpoints[0]
    assert not binding.complete
    assert binding.params == {}
    assert "requires an explicit semantic producer" in binding.residual_reasons[0]


def test_or_expression_is_not_partially_pushed_down():
    surface = parse_surface_script(
        "objects from lsst via demo\n"
        'where classification@lc_classifier.best.class = "SN" or '
        "classification@lc_classifier.best.probability >= 0.8\n"
    )

    report = bind_surface_predicates(
        surface,
        _generic_graph(),
        predicate_registry=_generic_registry(),
        semantic_paths=_SemanticPaths(),
    )

    binding = report.endpoints[0]
    assert not binding.complete
    assert binding.params == {}
    assert "only conjunctive" in binding.residual_reasons[0]


def test_mixed_and_expression_pushes_safe_subset_and_keeps_residual():
    surface = parse_surface_script(
        "objects from lsst via demo\n"
        'where classification@lc_classifier.best.class = "SN" and '
        "summary.time.last_mjd > 60000\n"
    )

    report = bind_surface_predicates(
        surface,
        _generic_graph(),
        predicate_registry=_generic_registry(),
        semantic_paths=_SemanticPaths(),
    )

    binding = report.endpoints[0]
    assert not binding.complete
    assert binding.params == {
        "class_name": "SN",
        "classifier": "lc_classifier",
    }
    assert len(binding.consumed_predicates) == 1
    assert len(binding.residual_reasons) == 1


def test_predicates_after_explicit_filter_are_not_candidate_pushdown():
    surface = parse_surface_script(
        """objects from lsst via demo
filter summary.time.last_mjd > 60000
with classification from lc_classifier:
    best.class = "SN"
"""
    )

    report = bind_surface_predicates(
        surface,
        _generic_graph(),
        predicate_registry=_generic_registry(),
        semantic_paths=_SemanticPaths(),
    )

    assert report.endpoints == ()


def test_reversed_comparison_normalizes_operator_before_binding():
    surface = parse_surface_script(
        "objects from lsst via demo\n"
        "where 0.8 <= classification@lc_classifier.best.probability\n"
    )

    report = bind_surface_predicates(
        surface,
        _generic_graph(),
        predicate_registry=_generic_registry(),
        semantic_paths=_SemanticPaths(),
    )

    assert report.complete_endpoints[0].params == {
        "classifier": "lc_classifier",
        "probability": 0.8,
    }
