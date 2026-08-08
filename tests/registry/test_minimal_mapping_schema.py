from pathlib import Path

import pytest
import yaml

from alertissimo.core.brokers.registry.mapping_schema import (
    MappingSchemaError,
    load_mapping_registry,
)


def _write(path: Path, data: object) -> Path:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def minimal_mapping() -> dict:
    return {
        "broker": "alerce",
        "origin": "lsst",
        "payloads": {
            "query_object": {"path": "."},
            "query_lightcurve.detections": {
                "endpoint": "query_lightcurve",
                "path": "detections[]",
            },
        },
        "mappings": {
            "summary@lsst:alerce.identity.object_id": ["query_object#oid"],
            "detection@lsst:alerce.time.mjd": [
                "query_lightcurve.detections#mjd"
            ],
        },
    }


@pytest.fixture
def registry_files(tmp_path: Path, minimal_mapping: dict) -> Path:
    _write(
        tmp_path / "endpoints.yaml",
        {"endpoints": {"query_object": {}, "query_lightcurve": {}}},
    )
    return _write(tmp_path / "mappings.yaml", minimal_mapping)


def test_valid_minimal_mapping_passes(registry_files: Path) -> None:
    loaded = load_mapping_registry(registry_files)
    assert loaded["broker"] == "alerce"


@pytest.mark.parametrize("forbidden", ["endpoints", "availability", "field_status"])
def test_per_mapping_forbidden_keys_fail(
    registry_files: Path, minimal_mapping: dict, forbidden: str
) -> None:
    feature = next(iter(minimal_mapping["mappings"]))
    minimal_mapping["mappings"][feature] = {forbidden: []}
    _write(registry_files, minimal_mapping)
    with pytest.raises(MappingSchemaError, match="forbidden"):
        load_mapping_registry(registry_files)


def test_payload_record_type_fails(registry_files: Path, minimal_mapping: dict) -> None:
    minimal_mapping["payloads"]["query_object"]["record_type"] = "object_summary"
    _write(registry_files, minimal_mapping)
    with pytest.raises(MappingSchemaError, match="record_type"):
        load_mapping_registry(registry_files)


def test_mapping_referencing_missing_payload_fails(
    registry_files: Path, minimal_mapping: dict
) -> None:
    feature = next(iter(minimal_mapping["mappings"]))
    minimal_mapping["mappings"][feature] = ["missing#oid"]
    _write(registry_files, minimal_mapping)
    with pytest.raises(MappingSchemaError, match="unknown payload"):
        load_mapping_registry(registry_files)


def test_unmapped_reference_with_missing_payload_fails(registry_files: Path) -> None:
    _write(
        registry_files.with_name("unmapped_fields.yaml"),
        {
            "broker": "alerce",
            "origin": "lsst",
            "unmapped": [
                {
                    "query_magstats#step_id_corr": {
                        "reason": "no_stable_feature_catalog_path"
                    }
                }
            ],
        },
    )
    with pytest.raises(MappingSchemaError, match="unknown payload"):
        load_mapping_registry(registry_files)


def test_payload_key_with_explicit_endpoint_passes(registry_files: Path) -> None:
    loaded = load_mapping_registry(registry_files)
    assert loaded["payloads"]["query_lightcurve.detections"]["endpoint"] == "query_lightcurve"


def test_payload_key_with_default_endpoint_passes(registry_files: Path) -> None:
    loaded = load_mapping_registry(registry_files)
    assert loaded["payloads"]["query_object"] == {"path": "."}
