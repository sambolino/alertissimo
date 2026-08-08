import subprocess
import sys

import pytest
import yaml

from alertissimo.core.brokers.registry.mapping_schema import (
    SchemaValidationError,
    main,
    validate_file,
    validate_mapping_data,
    validate_unmapped_data,
)


def valid_mapping():
    return {
        "broker": "demo",
        "origin": "ztf",
        "payloads": {"objects": {"path": ".", "endpoint": "query"}},
        "mappings": {"object@ztf:demo.id": ["objects#oid"]},
    }


@pytest.mark.parametrize("key", ["sources", "attribute_inventory", "mapping_policy"])
def test_unsupported_mapping_top_level_keys_fail(key):
    data = valid_mapping()
    data[key] = {}
    with pytest.raises(SchemaValidationError, match="unsupported top-level"):
        validate_mapping_data(data)


@pytest.mark.parametrize("key", ["bad#key", "bad key", ".bad", "bad."])
def test_invalid_payload_keys_fail(key):
    data = valid_mapping()
    data["payloads"] = {key: {"path": "."}}
    with pytest.raises(SchemaValidationError, match="invalid payload key"):
        validate_mapping_data(data)


def test_mapping_key_without_qualifier_fails():
    data = valid_mapping()
    data["mappings"] = {"object.id": ["objects#oid"]}
    with pytest.raises(SchemaValidationError, match="qualified semantic path"):
        validate_mapping_data(data)


def test_unknown_endpoint_fails_when_endpoint_names_are_known():
    with pytest.raises(SchemaValidationError, match="unknown endpoint"):
        validate_mapping_data(valid_mapping(), endpoint_names={"other"})


@pytest.mark.parametrize(
    "reference, message",
    [
        ("missing#oid", "unknown payload"),
        ("objects#oid#extra", "exactly one"),
        (" objects#oid", "whitespace around"),
        ("objects# oid", "whitespace around"),
    ],
)
def test_invalid_raw_references_fail(reference, message):
    data = valid_mapping()
    data["mappings"] = {"object@ztf:demo.id": [reference]}
    with pytest.raises(SchemaValidationError, match=message):
        validate_mapping_data(data)


def valid_unmapped():
    return {"broker": "demo", "origin": "ztf", "unmapped": [{"objects#x": {"reason": "unknown"}}]}


def test_unmapped_without_reason_fails():
    data = valid_unmapped()
    data["unmapped"][0]["objects#x"] = {"note": "later"}
    with pytest.raises(SchemaValidationError, match="reason"):
        validate_unmapped_data(data, valid_mapping())


@pytest.mark.parametrize("value", [None, "unknown", ["unknown"]])
def test_unmapped_invalid_value_type_fails(value):
    data = valid_unmapped()
    data["unmapped"][0]["objects#x"] = value
    with pytest.raises(SchemaValidationError, match="value must be a mapping"):
        validate_unmapped_data(data, valid_mapping())


@pytest.mark.parametrize("key", ["broker", "origin"])
def test_unmapped_identity_mismatch_fails(key):
    data = valid_unmapped()
    data[key] = "different"
    with pytest.raises(SchemaValidationError, match=f"{key} does not match"):
        validate_unmapped_data(data, valid_mapping())


def write_fixture(tmp_path, data):
    path = tmp_path / "mappings.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    (tmp_path / "endpoints.yaml").write_text(
        yaml.safe_dump({"endpoints": {"query": {}}}), encoding="utf-8"
    )
    return path


def test_validate_file_accepts_valid_fixture(tmp_path):
    validate_file(write_fixture(tmp_path, valid_mapping()))


def test_all_reports_legacy_files_as_skipped(capsys, monkeypatch, tmp_path):
    path = tmp_path / "broker" / "origin" / "mappings.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("broker: old\nmappings: {}\n", encoding="utf-8")
    monkeypatch.setattr(
        "alertissimo.core.brokers.registry.mapping_schema._registry_root", lambda: tmp_path
    )
    assert main(["--all"]) == 0
    output = capsys.readouterr().out
    assert "SKIPPED" in output
    assert "PASSED" not in output


def test_cli_exits_successfully_for_valid_fixture(tmp_path):
    path = write_fixture(tmp_path, valid_mapping())
    result = subprocess.run(
        [sys.executable, "-m", "alertissimo.core.brokers.registry.mapping_schema", str(path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "PASSED" in result.stdout


def test_cli_exits_nonzero_for_invalid_fixture(tmp_path):
    data = valid_mapping()
    data["sources"] = {}
    path = write_fixture(tmp_path, data)
    result = subprocess.run(
        [sys.executable, "-m", "alertissimo.core.brokers.registry.mapping_schema", str(path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "unsupported top-level" in result.stderr
