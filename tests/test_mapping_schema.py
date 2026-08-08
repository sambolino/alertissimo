import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from alertissimo.core.brokers.registry.mapping_schema import (
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
        "mappings": {"object@ztf:example.id": ["objects#oid"]},
    }


def test_valid_minimal_mapping_and_default_endpoint_pass(tmp_path, valid_mapping):
    write_yaml(tmp_path / "endpoints.yaml", {"endpoints": {"objects": {}}})
    validate_mapping_file(write_yaml(tmp_path / "mappings.yaml", valid_mapping))


def test_payload_with_explicit_endpoint_passes(tmp_path, valid_mapping):
    valid_mapping["payloads"] = {
        "query_object.detections": {"path": "detections", "endpoint": "query_object"}
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


def test_unknown_endpoint_fails_when_endpoints_file_present(tmp_path, valid_mapping):
    write_yaml(tmp_path / "endpoints.yaml", {"endpoints": {"other": {}}})
    with pytest.raises(MappingSchemaError, match="unknown endpoint"):
        validate_mapping_file(write_yaml(tmp_path / "mappings.yaml", valid_mapping))


@pytest.mark.parametrize(("semantic", "references", "match"), [
    ("object.id", ["objects#oid"], "invalid semantic path"),
    ("object@ztf:example.id", "objects#oid", "must be a non-empty list"),
    ("object@ztf:example.id", [], "must be a non-empty list"),
    ("object@ztf:example.id", ["missing#oid"], "unknown payload"),
    ("object@ztf:example.id", ["objects#oid#extra"], "exactly one"),
    ("object@ztf:example.id", ["objects #oid"], "whitespace around"),
    ("object@ztf:example.id", ["objects# oid"], "whitespace around"),
    ("object@ztf:example.id", ["objects#"], "non-empty payload and raw field"),
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
        [sys.executable, "-m", "alertissimo.core.brokers.registry.mapping_schema", str(path)],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0
    assert "PASSED" in result.stdout


def test_all_skips_legacy_files_without_payloads(tmp_path, monkeypatch, capsys):
    registry = tmp_path / "registry"
    path = registry / "broker" / "origin" / "mappings.yaml"
    path.parent.mkdir(parents=True)
    write_yaml(path, {"broker": "old", "origin": "ztf", "mappings": {}})
    monkeypatch.setattr(
        "alertissimo.core.brokers.registry.mapping_schema.__file__",
        str(registry / "mapping_schema.py"),
    )
    assert main(["--all"]) == 0
    output = capsys.readouterr().out
    assert "SKIPPED" in output
    assert "PASSED" not in output


ALERCE_REGISTRY = Path("alertissimo/core/brokers/registry/alerce")


@pytest.fixture(params=("lsst", "ztf"))
def alerce_mapping(request):
    directory = ALERCE_REGISTRY / request.param
    mapping = yaml.safe_load((directory / "mappings.yaml").read_text(encoding="utf-8"))
    unmapped = yaml.safe_load(
        (directory / "unmapped_fields.yaml").read_text(encoding="utf-8")
    )
    return mapping, unmapped


def test_alerce_lightcurve_rows_use_nested_payloads(alerce_mapping):
    mapping, _ = alerce_mapping
    forbidden_fields = {
        "ra", "dec", "mjd", "measurement_id", "psfFlux", "psfFluxErr",
        "scienceFlux", "templateFlux", "apFlux", "snr", "magpsf", "sigmapsf",
        "diffmaglim",
    }
    references_by_semantic = mapping["mappings"]
    references = {
        reference
        for semantic_references in references_by_semantic.values()
        for reference in semantic_references
    }

    assert not {f"query_lightcurve#{field}" for field in forbidden_fields} & references

    expected_payload = {
        "detection@": "query_lightcurve.detections",
        "forced_photometry@": "query_lightcurve.forced_photometry",
        "non_detection@": "query_lightcurve.non_detections",
    }
    nested_references = {payload: [] for payload in expected_payload.values()}
    for semantic, semantic_references in references_by_semantic.items():
        for prefix, payload in expected_payload.items():
            if semantic.startswith(prefix):
                lightcurve_references = [
                    reference
                    for reference in semantic_references
                    if reference.startswith("query_lightcurve")
                ]
                assert all(
                    reference.startswith(f"{payload}#")
                    for reference in lightcurve_references
                )
                nested_references[payload].extend(lightcurve_references)

    assert all(nested_references.values())


def test_alerce_mapped_references_are_not_also_unmapped(alerce_mapping):
    mapping, unmapped = alerce_mapping
    mapped_references = {
        reference
        for semantic_references in mapping["mappings"].values()
        for reference in semantic_references
    }
    unmapped_references = {
        next(iter(entry))
        for entry in unmapped["unmapped"]
    }
    assert mapped_references.isdisjoint(unmapped_references)
