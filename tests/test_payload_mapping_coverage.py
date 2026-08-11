import json
from pathlib import Path

import pytest

from tools.audit_payload_mapping_coverage import _leaf_paths, audit_payload

FIXTURES = Path(__file__).parent / "fixtures" / "lasair"
ENDPOINTS = {
    "ztf": ("object", "objects", "lightcurves", "cone", "query", "sherlock_objects", "sherlock_position"),
    "lsst": ("object", "cone", "query", "sherlock_object", "sherlock_position"),
}


@pytest.mark.parametrize(
    ("origin", "endpoint"),
    [(origin, endpoint) for origin, endpoints in ENDPOINTS.items() for endpoint in endpoints],
)
def test_every_registered_lasair_endpoint_fixture_is_fully_accounted(origin, endpoint):
    path = FIXTURES / origin / f"{endpoint}.json"
    report = audit_payload(
        json.loads(path.read_text()), broker="lasair", origin=origin,
        endpoint=endpoint, payload_file=str(path),
    )
    assert "Unaccounted leaves: 0" in report
    assert "Unaccounted leaves:\n  (none)" in report
    assert "Portfolio records:" in report


def test_recursive_audit_reports_concrete_unaccounted_candidate_leaf():
    payload = json.loads((FIXTURES / "ztf" / "object.json").read_text())
    payload["candidates"][0]["unexpected_leaf"] = 1
    report = audit_payload(payload, broker="lasair", origin="ztf", endpoint="object")
    assert "candidates#unexpected_leaf" in report
    assert "object#candidates" not in report


def test_cone_count_object_shape_selects_aggregate_payload_definition():
    path = FIXTURES / "ztf" / "cone_count.json"
    report = audit_payload(
        json.loads(path.read_text()), broker="lasair", origin="ztf",
        endpoint="cone", payload_file=str(path),
    )
    assert "cone_count: ." in report
    assert "cone: []" not in report
    assert "Unaccounted leaves: 0" in report


def test_scalar_classification_array_leaves_keep_indices():
    assert _leaf_paths({"_value": ["SN", "description"]}) == {
        "_value.0", "_value.1",
    }


def test_query_fixture_scope_is_explicitly_projection_specific():
    # Query columns are caller-selected; this fixture audits only its known projection.
    report = audit_payload(
        json.loads((FIXTURES / "ztf" / "query.json").read_text()),
        broker="lasair", origin="ztf", endpoint="query",
    )
    assert "Unaccounted leaves: 0" in report
