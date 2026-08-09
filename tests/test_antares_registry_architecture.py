from pathlib import Path

import pytest
import yaml

ROOT = Path("alertissimo/core/brokers/registry/antares")
ORIGINS = ("lsst", "ztf")
FORBIDDEN_ENDPOINT_KEYS = {
    "provides", "output_type", "binding", "input", "value_from", "capabilities",
    "required_bindings", "optional_bindings", "record_scope", "returns_science_data",
}
ALLOWED_MAPPING_KEYS = {
    "broker", "origin", "payloads", "mappings", "transforms", "description", "notes",
}
LEGACY_MAPPING_KEYS = {
    "field", "availability", "filter", "transform", "sources", "source_fields",
    "field_status", "endpoints", "record_type", "object_summary", "detection_rows",
    "capabilities",
}


def load(origin, filename):
    return yaml.safe_load((ROOT / origin / filename).read_text(encoding="utf-8"))


@pytest.mark.parametrize("origin", ORIGINS)
def test_physical_endpoints(origin):
    endpoints = load(origin, "endpoints.yaml")["endpoints"]
    for name, endpoint in endpoints.items():
        assert not FORBIDDEN_ENDPOINT_KEYS & endpoint.keys()
        assert endpoint["output"]["type"] in {"array", "object"}
        params = endpoint.get("params", {})
        for definition in params.values():
            assert isinstance(definition.get("description"), str)
            assert definition["description"].strip()
        assert set(endpoint.get("server_filters", [])) <= set(params)
        for operation in endpoint.get("operation_types", []):
            assert "@" not in operation
            assert "." not in operation


def test_no_antares_planner_terms():
    assert not list(ROOT.rglob("planner_terms.yaml"))


@pytest.mark.parametrize("origin", ORIGINS)
def test_minimal_mappings_and_payload_shapes(origin):
    document = load(origin, "mappings.yaml")
    endpoints = load(origin, "endpoints.yaml")["endpoints"]
    assert set(document) <= ALLOWED_MAPPING_KEYS
    payloads = document["payloads"]
    mapped = set()
    for name, payload in payloads.items():
        endpoint = payload["endpoint"]
        assert endpoint in endpoints
        assert payload["path"] == ("[]" if endpoints[endpoint]["output"]["type"] == "array" else ".")
        assert payload["path"] != "$"
        if "row_filter" in payload:
            assert endpoint in endpoints
    for semantic, refs in document["mappings"].items():
        assert isinstance(refs, list) and refs
        for ref in refs:
            payload, field = ref.split("#")
            assert payload in payloads and field
            mapped.add(ref)
        assert not (LEGACY_MAPPING_KEYS & set(refs))
    for semantic, specifications in document.get("transforms", {}).items():
        assert semantic in document["mappings"]
        assert set(specifications) <= set(document["mappings"][semantic])
    unmapped = load(origin, "unmapped_fields.yaml")["unmapped"]
    unmapped_refs = {next(iter(entry)) for entry in unmapped}
    assert mapped.isdisjoint(unmapped_refs)


def test_lsst_mappings_preserve_availability_and_transform():
    document = load("lsst", "mappings.yaml")
    mappings = document["mappings"]
    semantic = "summary@lsst:antares.identity.object_id"
    assert "loci#properties.survey.lsst.dia_object_id" in mappings[semantic]
    assert "locus#properties.survey.lsst.dia_object_id" in mappings[semantic]
    assert "detection@lsst:antares.image_metrics.shape.ixx" in mappings
    transform = document["transforms"]["detection@lsst:antares.image_metrics.is_positive"]
    assert transform["locus_alerts#properties.lsst_diaSource_isNegative"]["type"] == "boolean_not"


def test_ztf_mappings_preserve_filters_transforms_and_catalog_paths():
    document = load("ztf", "mappings.yaml")
    payloads, mappings = document["payloads"], document["mappings"]
    semantic = "summary@ztf:antares.identity.object_id"
    assert "loci#properties.ztf_object_id" in mappings[semantic]
    assert "locus#properties.ztf_object_id" in mappings[semantic]
    assert payloads["catalog_matches.gaia"]["row_filter"]["meta.catalog_name"] == "gaia_dr3_gaia_source"
    assert payloads["catalog_matches.allwise"]["row_filter"]["meta.catalog_name"] == "allwise"
    assert "catalog_matches.gaia#object_id" in mappings["crossmatch@gaia:antares.identity.object_id"]
    assert "catalog_matches.allwise#properties.w1mpro" in mappings["crossmatch@allwise:antares.photometry.W1.mag"]
    transform = document["transforms"]["detection@ztf:antares.image_metrics.is_positive"]
    assert transform["locus_alerts#properties.ztf_isdiffpos"]["type"] == "value_map"
    assert "detection@ztf:antares.quality.real_bogus" in mappings
    assert "detection@ztf:antares.reference_image.nearest_source.separation.total" in mappings
    assert "crossmatch@gaia:antares.astrometric_solution.parallax" in mappings
