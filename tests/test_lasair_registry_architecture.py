from pathlib import Path

import yaml


REGISTRY = Path("alertissimo/data_layer/providers/lasair")
ENDPOINT_KEYS = {
    "path", "method", "description", "headers", "params", "output",
    "operation_types", "server_filters", "post_filter", "projection",
    "enabled", "note", "notes",
}
FORBIDDEN_ENDPOINT_KEYS = {
    "provides", "output_type", "capabilities", "binding", "input",
    "value_from", "required_bindings", "optional_bindings", "record_scope",
    "returns_science_data",
}
MAPPING_KEYS = {
    "broker", "origin", "description", "notes", "payloads", "mappings",
    "transforms",
}
LEGACY_MAPPING_KEYS = {
    "field", "availability", "transform", "filter_field", "filter_transform",
    "producer_field",
}


def load(origin: str, filename: str) -> dict:
    with (REGISTRY / origin / filename).open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def test_endpoint_contracts_are_physical_rest_operations() -> None:
    expected = {
        "lsst": {
            "object", "cone", "query", "sherlock_object", "sherlock_position",
        },
        "ztf": {
            "object", "objects", "lightcurves", "cone", "query",
            "sherlock_objects", "sherlock_position",
        },
    }
    expected_baseurl = {
        "lsst": "https://api.lasair.lsst.ac.uk",
        "ztf": "https://lasair-ztf.lsst.ac.uk",
    }

    for origin in ("lsst", "ztf"):
        document = load(origin, "endpoints.yaml")
        endpoints = document["endpoints"]
        names = set(endpoints)
        if origin == "ztf" and "streams" in names:
            expected[origin].add("streams")
        assert names == expected[origin]
        assert document["baseurl"] == expected_baseurl[origin]

        for name, endpoint in endpoints.items():
            assert set(endpoint) <= ENDPOINT_KEYS
            assert not set(endpoint) & FORBIDDEN_ENDPOINT_KEYS
            assert endpoint["method"] == "POST"
            assert endpoint["path"].startswith("/api/")
            assert endpoint["description"].strip()
            assert endpoint["output"]["type"]
            assert all("@" not in operation for operation in endpoint["operation_types"])
            for specification in endpoint.get("params", {}).values():
                assert specification["description"].strip()
            for specification in endpoint.get("headers", {}).values():
                assert specification["description"].strip()
            assert set(endpoint.get("server_filters", [])) <= set(
                endpoint.get("params", {})
            )
            if name == "query":
                assert endpoint["projection"] == {
                    "supports_columns": True,
                    "param": "selected",
                }
                assert list(endpoint["params"]) == [
                    "selected", "tables", "conditions", "limit", "offset",
                ]
            else:
                assert endpoint["projection"] == {"supports_columns": False}


def test_mappings_use_minimal_payload_references() -> None:
    for origin in ("lsst", "ztf"):
        endpoints = load(origin, "endpoints.yaml")["endpoints"]
        document = load(origin, "mappings.yaml")
        assert set(document) <= MAPPING_KEYS
        payloads = document["payloads"]
        mappings = document["mappings"]
        mapped_refs = set()

        for payload in payloads.values():
            assert payload["endpoint"] in endpoints
            assert payload["path"] == "." or payload["path"].endswith(("[]", "{}"))
        for refs in mappings.values():
            assert isinstance(refs, list) and refs
            for ref in refs:
                assert isinstance(ref, str) and ref.count("#") == 1
                assert ref.split("#", 1)[0] in payloads
                mapped_refs.add(ref)

        def visit(value: object) -> None:
            if isinstance(value, dict):
                assert not set(value) & LEGACY_MAPPING_KEYS
                for nested in value.values():
                    visit(nested)
            elif isinstance(value, list):
                for nested in value:
                    visit(nested)

        visit(mappings)
        transforms = document.get("transforms", {})
        for semantic_path, raw_transforms in transforms.items():
            assert semantic_path in mappings
            assert set(raw_transforms) <= set(mappings[semantic_path])

        unmapped = load(origin, "unmapped_fields.yaml")["unmapped"]
        unmapped_refs = {next(iter(entry)) for entry in unmapped}
        assert mapped_refs.isdisjoint(unmapped_refs)


def test_singleton_context_is_rooted_in_object_payload() -> None:
    for origin in ("lsst", "ztf"):
        document = load(origin, "mappings.yaml")
        payloads = document["payloads"]
        mappings = document["mappings"]
        assert "sherlock" not in payloads
        assert "tns" not in payloads
        assert not any(
            ref.startswith("sherlock#") or ref.startswith("tns#")
            for refs in mappings.values()
            for ref in refs
        )


def test_lsst_context_and_collection_mappings() -> None:
    mappings = load("lsst", "mappings.yaml")["mappings"]
    assert mappings["classification@sherlock:lasair.best.class"][0] == (
        "object#lasairData.sherlock.classification"
    )
    assert mappings["crossmatch@tns:lasair.identity.object_id"] == [
        "object#lasairData.TNS.name"
    ]
    assert "lightcurve@lsst:lasair.{filter}.points" not in mappings


def test_ztf_context_collection_mappings_and_transforms() -> None:
    document = load("ztf", "mappings.yaml")
    mappings = document["mappings"]
    transforms = document["transforms"]
    assert mappings["classification@sherlock:lasair.best.class"] == [
        "object#sherlock.classification",
        "sherlock_position_classifications#_value.0",
        "sherlock_objects_classifications#_value.0",
    ]
    assert mappings["classification@sherlock:lasair.best.description"] == [
        "sherlock_position_classifications#_value.1",
        "sherlock_objects_classifications#_value.1",
    ]
    assert not any(
        key.startswith("classification@sherlock:lasair.")
        and key.endswith(("identity.object_id", "subject.object_id", "target.object_id"))
        for key in mappings
    )
    assert not any(
        ref.endswith("#_key")
        for key, refs in mappings.items()
        if key.startswith("classification@sherlock:lasair.")
        for ref in refs
    )
    assert "classification@sherlock:lasair.description" not in mappings
    assert mappings["classification@tns:lasair.best.class"] == ["object#TNS.type"]
    assert mappings["crossmatch@tns:lasair.identity.object_id"] == ["object#TNS.name"]
    assert "lightcurve@ztf:lasair.{filter}.points" not in mappings
    assert transforms["detection@ztf:lasair.time.mjd"]["candidates#jd"][
        "type"
    ] == "jd_to_mjd"
    assert transforms["detection@ztf:lasair.photometry.{filter}"][
        "candidates#fid"
    ]["type"] == "value_map"
    assert transforms["detection@ztf:lasair.image_metrics.is_positive"][
        "candidates#isdiffpos"
    ]["type"] == "value_map"
