import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from alertissimo.data_layer.runtime.mapping_schema import (
    MappingSchemaError,
    main,
    validate_mapping_file,
)


def write_yaml(path: Path, value) -> Path:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def valid_mapping():
    return {
        "broker": "example",
        "origin": "ztf",
        "description": "Minimal example",
        "notes": "Human-authored",
        "payloads": {"objects": {"path": ".", "description": "Rows"}},
        "mappings": {"summary@ztf:example.identity.object_id": ["objects#oid"]},
    }


def test_valid_minimal_mapping_and_default_endpoint_pass(tmp_path, valid_mapping):
    write_yaml(tmp_path / "endpoints.yaml", {"endpoints": {"objects": {}}})
    validate_mapping_file(write_yaml(tmp_path / "mappings.yaml", valid_mapping))


def test_reference_cannot_be_both_mapped_and_unmapped(tmp_path, valid_mapping):
    write_yaml(tmp_path / "endpoints.yaml", {"endpoints": {"objects": {}}})
    write_yaml(
        tmp_path / "unmapped_fields.yaml",
        {
            "broker": "example",
            "origin": "ztf",
            "unmapped": [{"objects#oid": {"reason": "unstable_semantics"}}],
        },
    )
    path = write_yaml(tmp_path / "mappings.yaml", valid_mapping)
    with pytest.raises(MappingSchemaError, match="both mapped and unmapped"):
        validate_mapping_file(path)


def test_payload_with_explicit_endpoint_passes(tmp_path, valid_mapping):
    valid_mapping["payloads"] = {
        "query_object.detections": {"path": "detections[]", "endpoint": "query_object"}
    }
    valid_mapping["mappings"] = {
        "detection@ztf:example.time.mjd": ["query_object.detections#mjd"]
    }
    write_yaml(tmp_path / "endpoints.yaml", {"endpoints": {"query_object": {}}})
    validate_mapping_file(write_yaml(tmp_path / "mappings.yaml", valid_mapping))


def test_valid_unmapped_fields_passes(tmp_path, valid_mapping):
    write_yaml(tmp_path / "unmapped_fields.yaml", {
        "broker": "example", "origin": "ztf", "notes": "Deferred",
        "unmapped": [{"objects#r:diaObjectId": {
            "reason": "No catalog feature yet", "note": "Review later",
            "candidate_meaning": "Object identifier",
        }}],
    })
    validate_mapping_file(write_yaml(tmp_path / "mappings.yaml", valid_mapping))


@pytest.mark.parametrize(("change", "match"), [
    (("pop", "broker"), "missing required key 'broker'"),
    (("set", "broker", ""), "broker must be a non-empty string"),
    (("pop", "origin"), "missing required key 'origin'"),
    (("set", "origin", "  "), "origin must be a non-empty string"),
    (("set", "sources", {}), "unsupported key"),
    (("set", "attribute_inventory", {}), "unsupported key"),
    (("set", "mapping_policy", {}), "unsupported key"),
    (("set", "description", []), "description must be a string"),
    (("set", "notes", {}), "notes must be a string"),
    (("pop", "payloads"), "missing required key 'payloads'"),
    (("set", "payloads", {}), "payloads must not be empty"),
])
def test_invalid_mapping_document_fails(tmp_path, valid_mapping, change, match):
    if change[0] == "pop":
        valid_mapping.pop(change[1])
    else:
        valid_mapping[change[1]] = change[2]
    with pytest.raises(MappingSchemaError, match=match):
        validate_mapping_file(write_yaml(tmp_path / "mappings.yaml", valid_mapping))


@pytest.mark.parametrize(("key", "definition", "match"), [
    ("bad#key", {"path": "."}, "valid payload key"),
    ("bad key", {"path": "."}, "valid payload key"),
    (".bad", {"path": "."}, "valid payload key"),
    ("bad.", {"path": "."}, "valid payload key"),
    ("objects", {"path": ".", "source_fields": []}, "unsupported key"),
    ("objects", {}, "missing required key 'path'"),
    ("objects", {"path": ""}, "path must be a non-empty string"),
])
def test_invalid_payload_fails(tmp_path, valid_mapping, key, definition, match):
    valid_mapping["payloads"] = {key: definition}
    valid_mapping["mappings"] = {}
    with pytest.raises(MappingSchemaError, match=match):
        validate_mapping_file(write_yaml(tmp_path / "mappings.yaml", valid_mapping))


@pytest.mark.parametrize(
    "path",
    [
        ".",
        "[]",
        "detections[]",
        "non_detections[]",
        "forced_photometry[]",
        "classifications{}",
        "[].classifications{}",
    ],
)
def test_supported_payload_paths_pass(tmp_path, valid_mapping, path):
    valid_mapping["payloads"]["objects"]["path"] = path
    validate_mapping_file(write_yaml(tmp_path / "mappings.yaml", valid_mapping))


@pytest.mark.parametrize(
    "path", ["$", "", "   ", "detections", "{}", "a[].b[]", "[].a{}.b{}"]
)
def test_unsupported_payload_paths_fail(tmp_path, valid_mapping, path):
    valid_mapping["payloads"]["objects"]["path"] = path
    with pytest.raises(MappingSchemaError, match="non-empty|string|collection path"):
        validate_mapping_file(write_yaml(tmp_path / "mappings.yaml", valid_mapping))


def test_unknown_endpoint_fails_when_endpoints_file_present(tmp_path, valid_mapping):
    write_yaml(tmp_path / "endpoints.yaml", {"endpoints": {"other": {}}})
    with pytest.raises(MappingSchemaError, match="unknown endpoint"):
        validate_mapping_file(write_yaml(tmp_path / "mappings.yaml", valid_mapping))


@pytest.mark.parametrize(("semantic", "references", "match"), [
    ("object.id", ["objects#oid"], "invalid semantic path"),
    ("summary@ztf:example.identity.object_id", "objects#oid", "must be a non-empty list"),
    ("summary@ztf:example.identity.object_id", [], "must be a non-empty list"),
    ("summary@ztf:example.identity.object_id", ["missing#oid"], "unknown payload"),
    ("summary@ztf:example.identity.object_id", ["objects#oid#extra"], "exactly one"),
    ("summary@ztf:example.identity.object_id", ["objects #oid"], "whitespace around"),
    ("summary@ztf:example.identity.object_id", ["objects# oid"], "whitespace around"),
    ("summary@ztf:example.identity.object_id", ["objects#"], "non-empty payload and raw field"),
])
def test_invalid_mapping_entry_fails(tmp_path, valid_mapping, semantic, references, match):
    valid_mapping["mappings"] = {semantic: references}
    with pytest.raises(MappingSchemaError, match=match):
        validate_mapping_file(write_yaml(tmp_path / "mappings.yaml", valid_mapping))


@pytest.mark.parametrize(("document", "match"), [
    ({"broker": "example", "origin": "ztf", "unmapped": [{"objects#x": {}}]},
     "missing required key 'reason'"),
    ({"broker": "example", "origin": "ztf", "unmapped": [{"objects#x": "later"}]},
     "value must be a mapping"),
    ({"broker": "different", "origin": "ztf", "unmapped": []}, "broker does not match"),
    ({"broker": "example", "origin": "lsst", "unmapped": []}, "origin does not match"),
    ({"broker": "example", "origin": "ztf", "unmapped": [{"missing#x": {"reason": "later"}}]},
     "unknown payload"),
])
def test_invalid_unmapped_file_fails(tmp_path, valid_mapping, document, match):
    write_yaml(tmp_path / "unmapped_fields.yaml", document)
    with pytest.raises(MappingSchemaError, match=match):
        validate_mapping_file(write_yaml(tmp_path / "mappings.yaml", valid_mapping))


def test_cli_succeeds_for_valid_fixture(tmp_path, valid_mapping):
    path = write_yaml(tmp_path / "mappings.yaml", valid_mapping)
    result = subprocess.run(
        [sys.executable, "-m", "alertissimo.data_layer.runtime.mapping_schema", str(path)],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0
    assert "PASSED" in result.stdout


def test_invalid_ontology_path_fails(tmp_path, valid_mapping):
    semantic = "classification@sherlock:lasair.description"
    valid_mapping["mappings"] = {semantic: ["objects#oid"]}

    with pytest.raises(MappingSchemaError, match="not reachable from ontology.yaml"):
        validate_mapping_file(write_yaml(tmp_path / "mappings.yaml", valid_mapping))


@pytest.mark.parametrize("origin", ["lsst", "ztf"])
def test_current_lasair_mapping_passes_ontology_validation(origin):
    path = (
        Path(__file__).parents[1]
        / "alertissimo/data_layer/providers/lasair"
        / origin
        / "mappings.yaml"
    )
    validate_mapping_file(path)


def test_all_skips_legacy_files_without_payloads(tmp_path, monkeypatch, capsys):
    data_layer = tmp_path / "data_layer"
    providers = data_layer / "providers"
    path = providers / "broker" / "origin" / "mappings.yaml"
    path.parent.mkdir(parents=True)
    write_yaml(path, {"broker": "old", "origin": "ztf", "mappings": {}})
    monkeypatch.setattr(
        "alertissimo.data_layer.runtime.mapping_schema.__file__",
        str(data_layer / "runtime" / "mapping_schema.py"),
    )
    assert main(["--all"]) == 0
    output = capsys.readouterr().out
    assert "SKIPPED" in output
    assert "PASSED" not in output


def test_payload_row_filter_accepts_scalar_values(tmp_path, valid_mapping):
    valid_mapping["payloads"]["objects"]["row_filter"] = {
        "meta.catalog_name": "gaia", "rank": 1, "active": True, "missing": None,
    }
    validate_mapping_file(write_yaml(tmp_path / "mappings.yaml", valid_mapping))


@pytest.mark.parametrize("value", [{"nested": "value"}, ["value"]])
def test_payload_row_filter_rejects_nested_values(tmp_path, valid_mapping, value):
    valid_mapping["payloads"]["objects"]["row_filter"] = {"meta": value}
    with pytest.raises(MappingSchemaError, match="row_filter values must be scalar"):
        validate_mapping_file(write_yaml(tmp_path / "mappings.yaml", valid_mapping))


def test_boolean_not_transform_without_map_passes(tmp_path, valid_mapping):
    semantic = "summary@ztf:example.identity.object_id"
    valid_mapping["transforms"] = {semantic: {"objects#oid": {"type": "boolean_not"}}}
    validate_mapping_file(write_yaml(tmp_path / "mappings.yaml", valid_mapping))


@pytest.mark.parametrize(
    "transform_type", ["to_string_strip", "to_float", "to_int", "jd_to_mjd"]
)
def test_new_transform_types_pass(tmp_path, valid_mapping, transform_type):
    semantic = "summary@ztf:example.identity.object_id"
    valid_mapping["transforms"] = {
        semantic: {"objects#oid": {"type": transform_type}}
    }
    validate_mapping_file(write_yaml(tmp_path / "mappings.yaml", valid_mapping))


def test_skip_null_boolean_passes(tmp_path, valid_mapping):
    semantic = "summary@ztf:example.identity.object_id"
    valid_mapping["transforms"] = {
        semantic: {"objects#oid": {"skip_null": True}}
    }
    validate_mapping_file(write_yaml(tmp_path / "mappings.yaml", valid_mapping))


def test_skip_null_non_boolean_fails(tmp_path, valid_mapping):
    semantic = "summary@ztf:example.identity.object_id"
    valid_mapping["transforms"] = {
        semantic: {"objects#oid": {"type": "to_float", "skip_null": "yes"}}
    }
    with pytest.raises(MappingSchemaError, match="skip_null must be boolean"):
        validate_mapping_file(write_yaml(tmp_path / "mappings.yaml", valid_mapping))


def test_value_map_default_passes(tmp_path, valid_mapping):
    semantic = "summary@ztf:example.identity.object_id"
    valid_mapping["transforms"] = {semantic: {"objects#oid": {
        "type": "value_map", "map": {"A": "star"}, "default": "unknown",
    }}}
    validate_mapping_file(write_yaml(tmp_path / "mappings.yaml", valid_mapping))


@pytest.mark.parametrize("default", [["unknown"], {"value": "unknown"}])
def test_default_non_scalar_fails(tmp_path, valid_mapping, default):
    semantic = "summary@ztf:example.identity.object_id"
    valid_mapping["transforms"] = {semantic: {"objects#oid": {
        "type": "value_map", "map": {}, "default": default,
    }}}
    with pytest.raises(MappingSchemaError, match="default must be scalar or null"):
        validate_mapping_file(write_yaml(tmp_path / "mappings.yaml", valid_mapping))


def test_unknown_transform_type_fails(tmp_path, valid_mapping):
    semantic = "summary@ztf:example.identity.object_id"
    valid_mapping["transforms"] = {
        semantic: {"objects#oid": {"type": "unknown"}}
    }
    with pytest.raises(MappingSchemaError, match="transform type"):
        validate_mapping_file(write_yaml(tmp_path / "mappings.yaml", valid_mapping))


@pytest.mark.parametrize(("transforms", "match"), [
    ({"summary@ztf:example.identity.missing": {"objects#oid": {"type": "boolean_not"}}}, "not in mappings"),
    ({"summary@ztf:example.identity.object_id": {"objects#other": {"type": "boolean_not"}}}, "not mapped under"),
    ({"summary@ztf:example.identity.object_id": {"objects#oid": {"type": "value_map"}}}, "requires 'map'"),
    ({"summary@ztf:example.identity.object_id": {"objects#oid": {"type": "unknown"}}}, "transform type"),
])
def test_invalid_transform_fails(tmp_path, valid_mapping, transforms, match):
    valid_mapping["transforms"] = transforms
    with pytest.raises(MappingSchemaError, match=match):
        validate_mapping_file(write_yaml(tmp_path / "mappings.yaml", valid_mapping))
