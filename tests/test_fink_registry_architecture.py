from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1] / "alertissimo/data_layer/providers/fink"
ORIGINS = ("lsst", "ztf")


def load(origin, name):
    return yaml.safe_load((ROOT / origin / name).read_text(encoding="utf-8"))


def test_payload_roots_match_endpoint_output_types():
    for origin in ORIGINS:
        mappings = load(origin, "mappings.yaml")
        endpoints = load(origin, "endpoints.yaml")["endpoints"]
        for name, payload in mappings["payloads"].items():
            assert payload["endpoint"] in endpoints
            expected = "[]" if endpoints[payload["endpoint"]]["output"]["type"] == "array" else "."
            assert payload["path"] == expected
            assert payload["path"] != "$"


def test_mappings_are_minimal_raw_reference_lists():
    for origin in ORIGINS:
        document = load(origin, "mappings.yaml")
        assert set(document) == {"broker", "origin", "payloads", "mappings"}
        for refs in document["mappings"].values():
            assert isinstance(refs, list) and refs
            assert all(isinstance(ref, str) and ref.count("#") == 1 for ref in refs)


def test_mapped_and_unmapped_are_disjoint_and_unmapped_is_real():
    for origin in ORIGINS:
        mapped = {ref for refs in load(origin, "mappings.yaml")["mappings"].values() for ref in refs}
        entries = load(origin, "unmapped_fields.yaml")["unmapped"]
        assert entries
        unmapped = {next(iter(entry)) for entry in entries}
        assert mapped.isdisjoint(unmapped)


def test_colons_in_raw_field_names_are_preserved():
    assert "objects#r:diaObjectId" in load("lsst", "mappings.yaml")["mappings"]["summary@lsst:fink.identity.object_id"]
    assert "statistics#basic:sci" in {ref for refs in load("ztf", "mappings.yaml")["mappings"].values() for ref in refs}


def test_cutout_mappings_are_data_products():
    for origin in ORIGINS:
        mappings = load(origin, "mappings.yaml")["mappings"]
        for path, refs in mappings.items():
            if any(ref.startswith("cutouts#") for ref in refs):
                assert path.startswith(f"data_product@{origin}:fink.")


def test_endpoints_are_physical_contracts():
    forbidden = {"binding", "input", "value_from", "capabilities"}
    allowed = {"path", "method", "description", "transport", "params", "output", "operation_types", "server_filters", "post_filter", "projection", "enabled", "note", "notes"}
    for origin in ORIGINS:
        for name, endpoint in load(origin, "endpoints.yaml")["endpoints"].items():
            assert not (set(endpoint) & forbidden), name
            assert set(endpoint) <= allowed, name
            params = endpoint.get("params", {})
            assert set(endpoint.get("server_filters", [])) <= set(params), name
            assert all("@" not in label for label in endpoint.get("operation_types", [])), name
            for param, definition in params.items():
                assert isinstance(definition.get("description"), str) and definition["description"].strip(), (name, param)
                assert not (set(definition) & {"binding", "input", "value_from"}), (name, param)


def test_fink_projection_metadata_matches_columns_param():
    for origin in ORIGINS:
        endpoints = load(origin, "endpoints.yaml")["endpoints"]
        for endpoint_name, endpoint in endpoints.items():
            params = endpoint.get("params", {})
            projection = endpoint.get("projection")
            if "columns" in params:
                assert params["columns"].get("role") == "projection", endpoint_name
                assert projection is not None, endpoint_name
                assert projection.get("supports_columns") is True, endpoint_name
                assert projection.get("param") == "columns", endpoint_name
            if projection and projection.get("supports_columns"):
                assert projection.get("param") in params, endpoint_name


def test_valid_fink_semantic_paths_are_preserved():
    ztf = load("ztf", "mappings.yaml")["mappings"]
    lsst = load("lsst", "mappings.yaml")["mappings"]
    for path in (
        "detection@ztf:fink.position.image_x", "detection@ztf:fink.position.image_y",
        "detection@ztf:fink.position.distance_to_edge", "detection@ztf:fink.separation.from_search_center",
        "detection@ztf:fink.calibration.{filter}.zero_point", "detection@ztf:fink.time.exposure",
        "detection@ztf:fink.quality.real_bogus",
    ):
        assert path in ztf
    assert "summary@lsst:fink.detection_count" in lsst


def test_lsst_summary_flags_are_mapped_and_not_unmapped():
    mappings = load("lsst", "mappings.yaml")["mappings"]
    unmapped_refs = {next(iter(entry)) for entry in load("lsst", "unmapped_fields.yaml")["unmapped"]}
    expected = {
        "summary@lsst:fink.flags.is_cataloged": {"objects#f:is_cataloged", "conesearch#f:is_cataloged"},
        "summary@lsst:fink.flags.is_first_detection": {"objects#f:is_first", "conesearch#f:is_first"},
        "summary@lsst:fink.flags.is_solar_system": {"objects#f:is_sso", "conesearch#f:is_sso"},
    }
    for path, refs in expected.items():
        assert set(mappings[path]) == refs
        assert not refs & unmapped_refs
