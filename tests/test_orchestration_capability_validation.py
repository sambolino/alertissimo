"""Tests for the read-only orchestration-to-registry capability bridge."""

from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraph,
    EndpointCapability,
    build_capability_graph,
)
from alertissimo.orchestration.ir.models import (
    ClassifyStep,
    ConeSearchStep,
    FilterStep,
    GetClassificationStep,
    GetCrossmatchStep,
    GetCutoutStep,
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
