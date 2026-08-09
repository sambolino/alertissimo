"""Tests for the normalized-registry capability graph."""

from dataclasses import fields

import pytest
import yaml

import alertissimo.core.brokers.registry.capabilities as capabilities
from alertissimo.core.brokers.registry.capabilities import (
    CapabilityGraphError,
    build_capability_graph,
)


def _write_minimal_registry(tmp_path, missing=None):
    registry = tmp_path / "example" / "ztf"
    registry.mkdir(parents=True)
    endpoint = {
        "path": "/api/object/",
        "method": "POST",
        "transport": {"path": "/legacy/object/", "method": "GET"},
        "params": {},
        "output": {"type": "object"},
        "operation_types": ["object_lookup"],
        "server_filters": [],
        "projection": {"supports_columns": False},
    }
    if missing is not None:
        endpoint.pop(missing)
    documents = {
        "endpoints.yaml": {
            "broker": "example",
            "origin": "ztf",
            "endpoints": {"object": endpoint},
        },
        "mappings.yaml": {
            "broker": "example",
            "origin": "ztf",
            "payloads": {},
            "mappings": {},
        },
        "unmapped_fields.yaml": {},
    }
    for filename, document in documents.items():
        (registry / filename).write_text(yaml.safe_dump(document), encoding="utf-8")


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


def test_endpoint_capability_uses_top_level_path_and_method(tmp_path):
    _write_minimal_registry(tmp_path)

    graph = build_capability_graph(tmp_path)
    endpoint = graph.endpoints_for("example", "ztf")[0]

    assert endpoint.path == "/api/object/"
    assert endpoint.method == "POST"


@pytest.mark.parametrize("missing", ["path", "method"])
def test_endpoint_capability_requires_top_level_path_and_method(tmp_path, missing):
    _write_minimal_registry(tmp_path, missing=missing)

    with pytest.raises(CapabilityGraphError, match=missing):
        build_capability_graph(tmp_path)


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
    records = {
        item.semantic_record_type
        for item in graph.semantic_record_capabilities
        if item.broker == "lasair" and item.origin == "ztf"
    }
    assert {
        "summary@ztf:lasair", "detection@ztf:lasair", "classification@lasair",
        "classification@tns:lasair", "crossmatch@tns:lasair",
        "crossmatch@{producer}:lasair",
    } <= records


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
