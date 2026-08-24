"""Tests for the read-only orchestration-to-registry capability bridge."""

from alertissimo.orchestration.ir import TargetSelector
import pytest

from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraph,
    EndpointCapability,
    SemanticRecordCapability,
    build_capability_graph,
)
from alertissimo.orchestration.ir.models import (
    ClassifyStep,
    ConeSearchStep,
    FilterStep,
    GetClassificationStep,
    GetCrossmatchStep,
    GetCutoutStep,
    GetDataProductStep,
    GetForcedPhotometryStep,
    GetLightcurveStep,
    GetSpectrumStep,
    LightcurveStep,
    LookupStep,
    MatchStep,
    MethodAnalysisStep,
    NotifyStep,
    SemanticSearchStep,
    Source,
    SqlQueryStep,
    WorkflowIR,
)
from alertissimo.orchestration.validation import (
    candidate_capabilities,
    validate_step_capabilities,
    validate_workflow_capabilities,
)


def test_cone_and_sql_require_their_registered_operations():
    graph = build_capability_graph()
    cone = ConeSearchStep(
        semantic_type="summary", ra=1, dec=2, radius=3,
        sources=[Source(broker="lasair", origin="ztf")],
    )
    sql = SqlQueryStep(
        semantic_type="summary", query="SELECT objectId",
        sources=[Source(broker="lasair", origin="ztf")],
    )
    assert {op for item in candidate_capabilities(cone, graph)
            for op in item.operation_types} >= {"cone_search"}
    assert {op for item in candidate_capabilities(sql, graph)
            for op in item.operation_types} >= {"sql_query"}


def test_semantic_search_checks_record_family_and_real_alerce_lsst_source():
    graph = build_capability_graph()
    supported = SemanticSearchStep(
        semantic_type="summary", criteria={"untranslated": True},
        sources=[Source(broker="alerce", origin="lsst")],
    )
    unsupported = supported.model_copy(update={"semantic_type": "spectrum"})
    assert validate_step_capabilities(supported, graph).status == "supported"
    assert validate_step_capabilities(unsupported, graph).status == "unsupported"


def test_each_explicit_source_must_be_supported():
    graph = build_capability_graph()
    step = SqlQueryStep(
        semantic_type="summary", query="SELECT 1",
        sources=[Source(broker="lasair", origin="ztf"), Source(broker="alerce")],
    )
    result = validate_step_capabilities(step, graph)
    assert result.status == "unsupported"
    assert [item.status for item in result.source_results] == ["supported", "unsupported"]


def test_full_lightcurve_does_not_accept_a_component_only_endpoint():
    component = EndpointCapability(
        "test", "ztf", "detections", "/detections", "GET",
        ("lightcurve_component",), (), (), None, False, "array",
    )
    graph = CapabilityGraph((component,), (), (), (), ())
    step = GetLightcurveStep(sources=[Source(broker="test")])
    assert validate_step_capabilities(step, graph).status == "unsupported"

    real = validate_step_capabilities(
        GetLightcurveStep(sources=[Source(broker="lasair", origin="ztf")]),
        build_capability_graph(),
    )
    assert real.status == "supported"
    assert {item.endpoint for item in real.candidates} == {"lightcurves"}


@pytest.mark.parametrize(
    ("broker", "origin", "endpoint"),
    [
        ("lasair", "lsst", "object"),
        ("antares", "ztf", "get_by_ztf_object_id"),
        ("antares", "lsst", "get_by_lsst_dia_object_id"),
    ],
)
def test_object_history_endpoints_can_realize_full_lightcurves(
    broker, origin, endpoint
):
    result = validate_step_capabilities(
        GetLightcurveStep(sources=[Source(broker=broker, origin=origin)]),
        build_capability_graph(),
    )
    assert result.status == "supported"
    assert {item.endpoint for item in result.candidates} == {endpoint}


def test_alerce_lsst_classification_retrieval_is_supported():
    graph = build_capability_graph()
    classification = validate_step_capabilities(
        GetClassificationStep(sources=[Source(broker="alerce", origin="lsst")]), graph
    )
    assert classification.status == "supported"


def test_lasair_ztf_classification_uses_generic_semantic_endpoints():
    classification = validate_step_capabilities(
        GetClassificationStep(sources=[Source(broker="lasair", origin="ztf")]),
        build_capability_graph(),
    )
    assert classification.status == "supported"
    assert {item.endpoint for item in classification.candidates} >= {
        "object", "objects", "sherlock_position", "sherlock_objects",
    }
    assert all(
        {"object_lookup", "context_lookup"}.intersection(item.operation_types)
        for item in classification.candidates
    )


@pytest.mark.parametrize("step_type", [GetClassificationStep, GetCrossmatchStep])
def test_lasair_sherlock_candidates_respect_target_cardinality(step_type):
    graph = build_capability_graph()
    ztf_source = [Source(broker="lasair", origin="ztf")]
    scalar = validate_step_capabilities(
        step_type(target=TargetSelector(ids=["A"], kind="object"), sources=ztf_source), graph
    )
    many = validate_step_capabilities(
        step_type(target=TargetSelector(ids=["A", "B"], kind="object"), sources=ztf_source), graph
    )
    assert "sherlock_object" in {item.endpoint for item in scalar.candidates}
    assert "sherlock_object" not in {item.endpoint for item in many.candidates}
    assert {"objects", "sherlock_objects"} <= {
        item.endpoint for item in many.candidates
    }

    lsst_many = validate_step_capabilities(
        step_type(
            target=TargetSelector(ids=["313761042336317573", "313761042336317574"], kind="object"),
            sources=[Source(broker="lasair", origin="lsst")],
        ),
        graph,
    )
    assert {item.endpoint for item in lsst_many.candidates} == {"sherlock_object"}


def test_lasair_sherlock_compiled_binding_roles():
    graph = build_capability_graph()
    capabilities = {
        (item.origin, item.endpoint): item
        for item in graph.endpoint_capabilities
        if item.broker == "lasair" and item.endpoint.startswith("sherlock_object")
    }
    assert capabilities[("ztf", "sherlock_object")].binding_roles == ("target_id",)
    assert capabilities[("ztf", "sherlock_object")].collection_binding_roles == ()
    assert capabilities[("ztf", "sherlock_objects")].binding_roles == ("target_id",)
    assert capabilities[("ztf", "sherlock_objects")].collection_binding_roles == ("target_id",)
    assert capabilities[("lsst", "sherlock_object")].binding_roles == ("target_id",)
    assert capabilities[("lsst", "sherlock_object")].collection_binding_roles == ("target_id",)


def test_classification_retrieval_requires_semantic_capability():
    non_classification = EndpointCapability(
        "test", "ztf", "object", "/object", "GET",
        ("object_lookup",), (), (), None, False, "object",
    )
    graph = CapabilityGraph((non_classification,), (), (), (), ())
    result = validate_step_capabilities(
        GetClassificationStep(sources=[Source(broker="test")]), graph
    )
    assert result.status == "unsupported"


def test_other_retrieval_rules_use_explicit_and_semantic_registry_evidence():
    graph = build_capability_graph()
    forced = validate_step_capabilities(
        GetForcedPhotometryStep(sources=[Source(broker="alerce", origin="lsst")]), graph
    )
    crossmatch = validate_step_capabilities(
        GetCrossmatchStep(sources=[Source(broker="lasair", origin="ztf")]), graph
    )
    assert forced.status == crossmatch.status == "supported"
    assert all("forced_photometry" in item.operation_types for item in forced.candidates)
    assert any("context_lookup" in item.operation_types for item in crossmatch.candidates)


def test_known_and_missing_data_products_report_cleanly():
    graph = build_capability_graph()
    cutout = validate_step_capabilities(
        GetCutoutStep(sources=[Source(broker="fink", origin="ztf")]), graph
    )
    spectrum = validate_step_capabilities(GetSpectrumStep(), graph)
    assert cutout.status == "supported"
    assert spectrum.status == "unsupported"
    assert "no compatible" in spectrum.source_results[0].reason


def test_lookup_and_local_steps_are_not_falsely_rejected():
    graph = build_capability_graph()
    lookup = validate_step_capabilities(
        LookupStep(id="namespace-not-yet-known", sources=[Source(broker="lasair")]), graph
    )
    assert lookup.status == "deferred"
    assert "identifier" in lookup.reason

    local_steps = [
        FilterStep(criteria={"x": 1}), LightcurveStep(), MatchStep(),
        MethodAnalysisStep(method="periodogram"), ClassifyStep(),
        NotifyStep(channel="email", message="done"),
    ]
    assert {
        validate_step_capabilities(step, graph).status for step in local_steps
    } == {"not_applicable"}


def test_classify_is_not_applicable_to_provider_capability_validation():
    result = validate_step_capabilities(ClassifyStep(), build_capability_graph())
    assert result.status == "not_applicable"


def test_workflow_validation_preserves_step_order():
    graph = build_capability_graph()
    workflow = WorkflowIR(steps=[
        ConeSearchStep(semantic_type="summary", ra=1, dec=2, radius=3),
        ClassifyStep(),
        GetSpectrumStep(),
    ])
    results = validate_workflow_capabilities(workflow, graph)
    assert [item.operation for item in results] == [
        "cone_search", "classify", "get_spectrum"
    ]
    assert [item.status for item in results] == [
        "supported", "not_applicable", "unsupported"
    ]


def test_multi_target_requires_explicit_collection_binding_evidence():
    graph = build_capability_graph()
    supported = validate_step_capabilities(
        GetLightcurveStep(target=TargetSelector(ids=["A", "B"], kind="object"), sources=[Source(broker="fink", origin="lsst")]), graph
    )
    rejected = validate_step_capabilities(
        GetLightcurveStep(target=TargetSelector(ids=["1", "2"], kind="object"), sources=[Source(broker="alerce", origin="lsst")]), graph
    )
    assert supported.status == "supported"
    assert {item.endpoint for item in supported.candidates} == {"sources"}
    assert rejected.status == "unsupported"
    assert "multi-target binding" in rejected.source_results[0].reason


def test_cardinality_filter_applies_to_cutout_and_data_product():
    graph = build_capability_graph()
    one = GetCutoutStep(target=TargetSelector(ids=["A"], kind="object"), sources=[Source(broker="fink", origin="ztf")])
    many = GetCutoutStep(target=TargetSelector(ids=["A", "B"], kind="object"), sources=one.sources)
    assert validate_step_capabilities(one, graph).status == "supported"
    rejected = validate_step_capabilities(many, graph)
    assert rejected.status == "unsupported"
    assert "multi-target binding" in rejected.source_results[0].reason

    singular_product = EndpointCapability(
        "test", "ztf", "product", "/product", "GET",
        ("data_product_lookup",), (), (), None, False, "object",
        ("target_id",), (),
    )
    product_graph = CapabilityGraph((singular_product,), (), (), (), ())
    product = GetDataProductStep(
        target=TargetSelector(ids=["A", "B"], kind="object"), sources=[Source(broker="test", origin="ztf")]
    )
    product_result = validate_step_capabilities(product, product_graph)
    assert product_result.status == "unsupported"
    assert "multi-target binding" in product_result.source_results[0].reason


def _semantic_target_graph(noun):
    singular = EndpointCapability(
        "test", "ztf", f"{noun}_one", "/one", "GET",
        ("context_lookup",), (), (), None, False, "object",
        ("target_id",), (),
    )
    collection = EndpointCapability(
        "test", "ztf", f"{noun}_many", "/many", "GET",
        ("context_lookup",), (), (), None, False, "array",
        ("target_id",), ("target_id",),
    )
    records = (SemanticRecordCapability(
        "test", "ztf", noun, (singular.endpoint, collection.endpoint), (),
    ),)
    return CapabilityGraph((singular, collection), (), (), (), records)


@pytest.mark.parametrize(("step_type", "noun"), [
    (GetClassificationStep, "classification"),
    (GetCrossmatchStep, "crossmatch"),
])
def test_semantic_gets_filter_singular_candidates_for_multiple_targets(step_type, noun):
    graph = _semantic_target_graph(noun)
    source = [Source(broker="test", origin="ztf")]
    scalar = validate_step_capabilities(step_type(target=TargetSelector(ids=["A"], kind="object"), sources=source), graph)
    many = validate_step_capabilities(step_type(target=TargetSelector(ids=["A", "B"], kind="object"), sources=source), graph)
    assert {item.endpoint for item in scalar.candidates} == {f"{noun}_one", f"{noun}_many"}
    assert {item.endpoint for item in many.candidates} == {f"{noun}_many"}

    singular_graph = CapabilityGraph((graph.endpoint_capabilities[0],), (), (), (), (
        graph.semantic_record_capabilities[0].__class__(
            "test", "ztf", noun, (f"{noun}_one",), ()
        ),
    ))
    rejected = validate_step_capabilities(step_type(target=TargetSelector(ids=["A", "B"], kind="object"), sources=source), singular_graph)
    assert rejected.status == "unsupported"
    assert "multi-target binding" in rejected.source_results[0].reason


def test_multi_target_spectrum_retains_semantic_absence_reason():
    result = validate_step_capabilities(GetSpectrumStep(target=TargetSelector(ids=["A", "B"], kind="object")), build_capability_graph())
    assert result.status == "unsupported"
    assert result.source_results[0].reason == "no compatible registered endpoint capability found"
