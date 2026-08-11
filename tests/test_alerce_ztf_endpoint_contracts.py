"""Regression checks for physical contracts against authoritative client bytes."""

from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests/fixtures/alerce/ztf"
REGISTRY = ROOT / "alertissimo/data_layer/providers/alerce/ztf/endpoints.yaml"
CAPTURED_ARRAY_ENDPOINTS = (
    "query_detections",
    "query_non_detections",
    "query_forced_photometry",
    "query_probabilities",
    "query_magstats",
    "query_features",
)


def _fixture(endpoint: str):
    return json.loads((FIXTURES / f"{endpoint}.json").read_bytes())


def _registry():
    return yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))


def _endpoints():
    return _registry()["endpoints"]


def _row_field_union(rows: list[dict]) -> set[str]:
    return set().union(*(row.keys() for row in rows)) if rows else set()


def test_authoritative_capture_metadata_matches_the_committed_manifest():
    capture = _registry()["authoritative_capture"]
    manifest = json.loads((FIXTURES / "capture_rest_manifest.json").read_bytes())

    assert capture["package"] == manifest["client_package"]
    assert capture["version"] == manifest["client_version"]
    assert capture["client"] == manifest["client"]
    assert capture["survey"] == manifest["survey"]
    assert capture["format"] == manifest["format"]
    assert set(manifest["calls"]) < set(capture["endpoints"])


def test_query_objects_contract_preserves_the_observed_wrapper():
    payload = _fixture("query_objects")
    endpoint = _endpoints()["query_objects"]
    audit = endpoint["audit"]

    assert endpoint["output"]["type"] == "object"
    assert set(endpoint["output"]["fields"]) == set(payload)
    assert endpoint["output"]["fields"]["items"] == {
        "type": "array",
        "item": "object_summary",
    }

    # ALeRCE documents these pagination values as integers, while this
    # authoritative response serializes them as null.
    for field in ("total", "page", "next", "prev"):
        assert endpoint["output"]["fields"][field] == {
            "type": "integer",
            "nullable": True,
        }
        assert payload[field] is None

    assert audit["capture_oids"] == [row["oid"] for row in payload["items"]]
    assert audit["observed_row_count"] == len(payload["items"])
    assert audit["observed_top_field_count"] == len(payload)
    assert audit["observed_flat_field_count"] == (
        len(payload) + len(_row_field_union(payload["items"]))
    )


def test_array_endpoint_audits_are_derived_from_authoritative_rows():
    endpoints = _endpoints()
    manifest = json.loads((FIXTURES / "capture_rest_manifest.json").read_bytes())

    for name in CAPTURED_ARRAY_ENDPOINTS:
        payload = _fixture(name)
        endpoint = endpoints[name]
        audit = endpoint["audit"]
        observed_fields = len(_row_field_union(payload))

        assert endpoint["output"]["type"] == "array", name
        assert audit["selected_oid"] == manifest["calls"][name]["object"], name
        assert audit["observed_row_count"] == len(payload), name
        assert audit["observed_top_field_count"] == observed_fields, name
        assert audit["observed_flat_field_count"] == observed_fields, name


def test_query_object_audit_is_derived_from_authoritative_object():
    payload = _fixture("query_object")
    audit = _endpoints()["query_object"]["audit"]

    assert audit["selected_oid"] == payload["oid"]
    assert audit["observed_top_field_count"] == len(payload)
    assert audit["observed_flat_field_count"] == len(payload)


def test_lightcurve_contract_counts_nested_fields_and_excludes_forced_photometry():
    payload = _fixture("query_lightcurve")
    endpoint = _endpoints()["query_lightcurve"]
    audit = endpoint["audit"]
    manifest = json.loads((FIXTURES / "capture_rest_manifest.json").read_bytes())
    branch_fields = {
        branch: _row_field_union(rows) for branch, rows in payload.items()
    }

    assert set(payload) == {"detections", "non_detections"}
    assert set(endpoint["output"]["fields"]) == set(payload)
    assert "forced_photometry" not in endpoint["output"]["fields"]
    assert "ztf_forced_photometry" not in audit["documented_models"]
    assert audit["selected_oid"] == manifest["calls"]["query_lightcurve"]["object"]
    for branch, rows in payload.items():
        assert audit["observed_branches"][branch] == {
            "row_count": len(rows),
            "observed_field_count": len(branch_fields[branch]),
        }

    # "top" counts the row-field unions; "flat" also counts branch containers.
    nested_field_count = sum(map(len, branch_fields.values()))
    assert audit["observed_top_field_count"] == nested_field_count
    assert audit["observed_flat_field_count"] == nested_field_count + len(payload)
