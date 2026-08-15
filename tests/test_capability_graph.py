"""Tests for the normalized-registry capability graph."""

from dataclasses import fields

import alertissimo.data_layer.runtime.capability_graph as capabilities
from alertissimo.data_layer.runtime.capability_graph import (
    build_capability_graph,
    canonical_semantic_noun,
    semantic_record_noun_matches,
)


def test_graph_builds_for_all_normalized_registries():
    graph = build_capability_graph()
    assert graph.endpoint_capabilities
    assert graph.payload_capabilities
    assert graph.field_mapping_capabilities
    assert graph.semantic_record_capabilities
    assert {(item.broker, item.origin) for item in graph.endpoint_capabilities} == {
        (broker, origin)
        for broker in ("alerce", "antares", "fink", "lasair")
        for origin in ("lsst", "ztf")
    }


def test_lasair_ztf_endpoint_capabilities_and_projection():
    graph = build_capability_graph()
    endpoints = {item.endpoint: item for item in graph.endpoints_for("lasair", "ztf")}
    assert {
        "object", "objects", "lightcurves", "cone", "query",
        "sherlock_objects", "sherlock_position",
    } <= endpoints.keys()
    assert endpoints["query"].supports_projection is True
    assert endpoints["query"].projection_param == "selected"
    assert endpoints["object"].supports_projection is False
    assert endpoints["object"].projection_param is None


def test_lasair_ztf_semantic_records():
    graph = build_capability_graph()
    semantic_types = {
        item.semantic_record_type
        for item in graph.semantic_record_capabilities
        if item.broker == "lasair" and item.origin == "ztf"
    }
    assert {
        "summary@ztf:lasair", "detection@ztf:lasair", "classification@lasair",
        "classification@tns:lasair", "crossmatch@tns:lasair",
        "crossmatch@{producer}:lasair",
    } <= semantic_types
    assert "crossmatch@{producer}:lasair" in semantic_types
    assert "crossmatch@unknown:lasair" not in semantic_types
    assert "crossmatch@sherlock:lasair" not in semantic_types


def test_semantic_paths_are_split_at_first_dot():
    graph = build_capability_graph()
    expected = {
        "detection@ztf:lasair.photometry.{filter}.psf.mag": (
            "detection@ztf:lasair", "photometry.{filter}.psf.mag"
        ),
        "classification@lsst:alerce.assessment.{output}.probability": (
            "classification@lsst:alerce", "assessment.{output}.probability"
        ),
    }
    for path, split in expected.items():
        matches = [item for item in graph.field_mapping_capabilities if item.semantic_path == path]
        assert matches
        assert {(item.semantic_record_type, item.relative_field_path) for item in matches} == {split}


def test_lasair_ztf_payload_and_raw_references():
    graph = build_capability_graph()
    mappings = {
        item.raw_ref: item.endpoint
        for item in graph.field_mapping_capabilities
        if item.broker == "lasair"
        and item.origin == "ztf"
        and item.semantic_path == "detection@ztf:lasair.photometry.{filter}.psf.mag"
    }
    assert mappings == {
        "candidates#magpsf": "object",
        "lightcurve_candidates#magpsf": "lightcurves",
    }


def test_lasair_ztf_transforms():
    graph = build_capability_graph()
    mjd = graph.transforms_for("detection@ztf:lasair.time.mjd")
    assert {(item.raw_ref, item.transform_type) for item in mjd} == {
        ("candidates#jd", "jd_to_mjd"),
        ("lightcurve_candidates#jd", "jd_to_mjd"),
    }
    filters = graph.transforms_for("detection@ztf:lasair.photometry.{filter}")
    assert {(item.raw_ref, item.transform_type) for item in filters} == {
        ("candidates#fid", "value_map"),
        ("lightcurve_candidates#fid", "value_map"),
    }


def test_capability_graph_does_not_define_portfolio_records():
    graph = build_capability_graph()
    assert not hasattr(capabilities, "Portfolio")
    assert not hasattr(capabilities, "SemanticRecord")
    for capability_type in (
        capabilities.EndpointCapability,
        capabilities.PayloadCapability,
        capabilities.FieldMappingCapability,
        capabilities.TransformCapability,
        capabilities.SemanticRecordCapability,
        capabilities.CapabilityGraph,
    ):
        assert "record_id" not in {field.name for field in fields(capability_type)}
    assert not hasattr(graph, "record_id")


def test_canonical_semantic_nouns_preserve_qualified_graph_types():
    assert canonical_semantic_noun("summary@ztf:lasair") == "summary"
    assert canonical_semantic_noun("detection@lsst:fink") == "detection"
    assert canonical_semantic_noun("crossmatch@gaia:fink") == "crossmatch"
    assert semantic_record_noun_matches("crossmatch@gaia:fink", "crossmatch")
    assert not semantic_record_noun_matches("crossmatch@gaia:fink", "summary")


def test_generic_endpoint_query_combines_source_operation_and_semantics():
    graph = build_capability_graph()
    unconstrained = graph.query_endpoints(operation_type="cone_search")
    broker = graph.query_endpoints(broker="lasair", operation_type="cone_search")
    origin = graph.query_endpoints(origin="lsst", operation_type="cone_search")
    exact = graph.query_endpoints(
        broker="lasair", origin="ztf", operation_type="cone_search",
        semantic_record_noun="summary",
    )
    assert unconstrained
    assert broker and {item.broker for item in broker} == {"lasair"}
    assert origin and {item.origin for item in origin} == {"lsst"}
    assert [(item.broker, item.origin, item.endpoint) for item in exact] == [
        ("lasair", "ztf", "cone")
    ]
