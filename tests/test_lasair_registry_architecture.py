from pathlib import Path

import pytest
import yaml


ROOT = Path("alertissimo/core/brokers/registry/lasair")
ORIGINS = ("lsst", "ztf")
EXPECTED_ENDPOINTS = {
    "lsst": {"cone", "query", "object", "sherlock_object", "sherlock_position"},
    "ztf": {"cone", "query", "object", "objects", "lightcurves", "sherlock_objects", "sherlock_position"},
}
FORBIDDEN_ENDPOINT_KEYS = {
    "provides", "output_type", "capabilities", "binding", "input", "value_from",
    "required_bindings", "optional_bindings", "record_scope", "returns_science_data",
}
ALLOWED_MAPPING_KEYS = {"broker", "origin", "payloads", "mappings", "transforms", "notes", "description"}
LEGACY_MAPPING_KEYS = {"field", "availability", "transform", "filter_field", "filter_transform", "producer_field"}


def load(origin, filename):
    return yaml.safe_load((ROOT / origin / filename).read_text(encoding="utf-8"))


@pytest.mark.parametrize("origin", ORIGINS)
def test_rest_endpoint_contracts(origin):
    endpoints = load(origin, "endpoints.yaml")["endpoints"]
    assert set(endpoints) == EXPECTED_ENDPOINTS[origin]
    for name, endpoint in endpoints.items():
        assert not FORBIDDEN_ENDPOINT_KEYS & endpoint.keys()
        assert endpoint["method"] == "POST"
        assert endpoint["path"].startswith("/api/")
        assert endpoint["output"]["type"]
        params = endpoint.get("params", {})
        assert all(specification.get("description", "").strip() for specification in params.values())
        assert all(specification.get("description", "").strip() for specification in endpoint.get("headers", {}).values())
        assert set(endpoint.get("server_filters", [])) <= set(params)
        assert all("@" not in operation for operation in endpoint.get("operation_types", []))
        projection = endpoint["projection"]
        if name == "query":
            assert projection == {"supports_columns": True, "param": "selected"}
        else:
            assert projection == {"supports_columns": False}


@pytest.mark.parametrize("origin", ORIGINS)
def test_minimal_payload_reference_mappings(origin):
    document = load(origin, "mappings.yaml")
    endpoints = load(origin, "endpoints.yaml")["endpoints"]
    assert set(document) <= ALLOWED_MAPPING_KEYS
    assert document["payloads"]
    for payload in document["payloads"].values():
        assert payload["endpoint"] in endpoints
        assert payload["path"] == "." or payload["path"].endswith("[]")

    mapped = set()
    for references in document["mappings"].values():
        assert isinstance(references, list) and references
        assert not any(isinstance(reference, dict) and LEGACY_MAPPING_KEYS & reference.keys() for reference in references)
        for reference in references:
            payload, field = reference.split("#")
            assert payload in document["payloads"] and field
            mapped.add(reference)

    unmapped = load(origin, "unmapped_fields.yaml")["unmapped"]
    assert mapped.isdisjoint(next(iter(entry)) for entry in unmapped)
    for semantic, specifications in document.get("transforms", {}).items():
        assert semantic in document["mappings"]
        assert set(specifications) <= set(document["mappings"][semantic])


def test_lsst_mappings_and_endpoint_limits():
    document = load("lsst", "mappings.yaml")
    mappings = document["mappings"]
    assert "objects" not in EXPECTED_ENDPOINTS["lsst"]
    assert "lightcurves" not in EXPECTED_ENDPOINTS["lsst"]
    assert "object#diaObjectId" in mappings["summary@lsst:lasair.identity.object_id"]
    assert "diaSourcesList#diaSourceId" in mappings["detection@lsst:lasair.identity.source_id"]
    assert "diaSourcesList#midpointMjdTai" in mappings["detection@lsst:lasair.time.mjd"]
    assert mappings["classification@lasair.assessment.sherlock.class"] == ["sherlock#classification"]
    assert mappings["crossmatch@tns:lasair.identity.object_id"] == ["tns#name"]


def test_ztf_mappings_and_transforms():
    document = load("ztf", "mappings.yaml")
    mappings = document["mappings"]
    transforms = document["transforms"]
    assert {"objects", "lightcurves"} <= EXPECTED_ENDPOINTS["ztf"]
    assert "object#objectId" in mappings["summary@ztf:lasair.identity.object_id"]
    assert "candidates#candid" in mappings["detection@ztf:lasair.identity.source_id"]
    assert "candidates#jd" in mappings["detection@ztf:lasair.time.mjd"]
    assert "candidates#fid" in mappings["detection@ztf:lasair.photometry.{filter}"]
    assert "candidates#isdiffpos" in mappings["detection@ztf:lasair.image_metrics.is_positive"]
    assert transforms["detection@ztf:lasair.time.mjd"]["candidates#jd"]["type"] == "jd_to_mjd"
    assert transforms["detection@ztf:lasair.photometry.{filter}"]["candidates#fid"]["type"] == "value_map"
    assert transforms["detection@ztf:lasair.image_metrics.is_positive"]["candidates#isdiffpos"]["type"] == "value_map"
