"""Semantic audit of the byte-frozen 2026-08-12 Fink/ZTF API evidence."""
from __future__ import annotations

import copy
import hashlib
import json
from itertools import count
from pathlib import Path

import pytest
import yaml

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance, InternalPortfolioId, InternalRecordId
from alertissimo.data_layer.runtime.mapping_schema import validate_mapping_file
from alertissimo.data_layer.runtime.record_builder import build_portfolio_from_execution

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests/fixtures/fink/ztf"
MAPPINGS = ROOT / "alertissimo/data_layer/providers/fink/ztf/mappings.yaml"
UNMAPPED = MAPPINGS.with_name("unmapped_fields.yaml")
PAYLOADS = {
    "objects_core": "objects", "objects_withupperlim": "objects", "conesearch": "conesearch",
    "latests": "latests", "anomaly": "anomaly", "sso_core": "sso", "resolver_tns": "resolver",
    "resolver_simbad": "resolver", "resolver_ssodnet": "resolver", "statistics_day": "statistics",
}
EXPECTED = {
    "objects_core": (14, 136), "objects_withupperlim": (33, 137), "conesearch": (1, 15),
    "latests": (10, 57), "anomaly": (10, 142), "sso_core": (327, 88), "resolver_tns": (1, 7),
    "resolver_simbad": (1, 11), "resolver_ssodnet": (4, 3), "statistics_day": (1, 131),
}


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def registry():
    return yaml.safe_load(MAPPINGS.read_text(encoding="utf-8"))


def _build(endpoint, payload):
    ids = count()
    return build_portfolio_from_execution(
        ExecutionResult(payload=payload, execution_provenance=InternalExecutionProvenance(
            internal_execution_id=InternalExecutionId(f"execution:fixture:{endpoint}"), broker="fink", origin="ztf", endpoint=endpoint)),
        mappings_path=MAPPINGS, internal_portfolio_id=InternalPortfolioId("portfolio:fixture"),
        record_id_factory=lambda: InternalRecordId(f"record:{next(ids)}"), validate_semantic_model=True)


def _detection_fields(portfolio):
    return [dict(record.fields) for record in portfolio.records if record.semantic_type == "detection@ztf:fink"]


def test_fixture_hashes_inventory_and_observed_domains():
    checksums = {}
    for line in (FIXTURES / "SHA256SUMS.txt").read_text().splitlines():
        digest, name = line.split(maxsplit=1); checksums[name.lstrip("* ")] = digest
    for stem, (rows, columns) in EXPECTED.items():
        path = FIXTURES / f"{stem}.json"; payload = fixture(stem)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == checksums[path.name]
        assert len(payload) == rows
        assert len({key for row in payload for key in row}) == columns
    tags = [row["d:tag"] for row in fixture("objects_withupperlim")]
    assert (tags.count("valid"), tags.count("upperlim")) == (14, 19)
    assert {row["i:fid"] for row in fixture("objects_core")} == {1, 2}
    assert {row["i:isdiffpos"] for row in fixture("objects_core")} == {"t"}


def test_zero_unaccounted_scalar_fields_per_frozen_payload():
    doc = registry(); mapped = {ref for refs in doc["mappings"].values() for ref in refs}
    debt = {next(iter(entry)) for entry in yaml.safe_load(UNMAPPED.read_text())["unmapped"]}
    assert mapped.isdisjoint(debt)
    for stem, payload_key in PAYLOADS.items():
        observed = {f"{payload_key}#{key}" for row in fixture(stem) for key, value in row.items() if not isinstance(value, (dict, list))}
        assert observed <= mapped | debt, (stem, sorted(observed - mapped - debt))


def test_fid_jd_isdiffpos_and_upper_limit_are_normalized():
    rows = fixture("objects_core")
    fields = _detection_fields(_build("objects", rows))
    by_alert = {field["identity.alert_id"]: field for field in fields}
    for row in rows:
        field = by_alert[row["i:candid"]]; band = {1: "g", 2: "r"}[row["i:fid"]]
        assert field["time.mjd"] == row["i:jd"] - 2400000.5
        assert field["image_metrics.is_positive"] is True
        assert f"photometry.{band}.psf.mag" in field
        assert not any("{filter}" in key or key.startswith("photometry.1") or key.startswith("photometry.2") for key in field)
        assert field.get(f"photometry.{band}.limit.upper_limit") is not True


def test_documented_synthetic_fid_and_false_encodings_are_strict():
    row = copy.deepcopy(fixture("objects_core")[0]); row["i:fid"] = 3; row["i:isdiffpos"] = "f"
    field = _detection_fields(_build("objects", [row]))[0]
    assert "photometry.i.psf.mag" in field and field["image_metrics.is_positive"] is False
    row["i:fid"] = 4; row["i:isdiffpos"] = "unexpected"
    field = _detection_fields(_build("objects", [row]))[0]
    assert not any(key.startswith("photometry.") for key in field)
    assert "image_metrics.is_positive" not in field


def test_upper_limit_rows_emit_only_meaningful_photometry_and_badquality_is_not_valid():
    upper = next(row for row in fixture("objects_withupperlim") if row["d:tag"] == "upperlim")
    field = _detection_fields(_build("objects", [upper]))[0]
    assert field["photometry.g.limit.upper_limit"] is True
    assert isinstance(field["photometry.g.limit.mag"], float)
    assert not any(token in key for key in field for token in (".psf.mag", ".aperture.mag"))
    bad = copy.deepcopy(upper); bad["d:tag"] = "badquality"; bad["i:magpsf"] = None
    field = _detection_fields(_build("objects", [bad]))[0]
    assert not any(key.endswith("upper_limit") for key in field)
    assert not any(".psf.mag" in key or ".aperture.mag" in key for key in field)


def test_cone_identity_and_degree_to_arcsec_scale():
    row = fixture("conesearch")[0]
    field = _detection_fields(_build("conesearch", [row]))[0]
    assert row["i:objectId"] == "ZTF21abfmbix" and field["identity.alert_id"] == 1642249732315015013
    assert field["separation.from_search_center"] == 0.0
    synthetic = copy.deepcopy(row); synthetic["v:separation_degree"] = 0.25
    assert _detection_fields(_build("conesearch", [synthetic]))[0]["separation.from_search_center"] == 900.0


def test_conservative_debt_does_not_fabricate_semantics():
    mappings = registry()["mappings"]
    assert "crossmatch@panstarrs:fink" not in mappings
    assert not any(path.startswith("portfolio.survey@") for path in mappings)
    assert not _build("statistics", fixture("statistics_day")).records
    for name in ("resolver_tns", "resolver_simbad", "resolver_ssodnet"):
        assert not _build("resolver", fixture(name)).records
    # Classifier -1 and catalog absence tokens remain explicit debt, not emitted scores/objects.
    anomaly = _build("anomaly", fixture("anomaly")[:1])
    assert not any(record.semantic_type.startswith(("classification@", "crossmatch@")) for record in anomaly.records)
    debt = {next(iter(entry)) for entry in yaml.safe_load(UNMAPPED.read_text())["unmapped"]}
    assert {"sso#sso_name", "sso#sso_number", "objects#i:ssnamenr"} <= debt


def test_registry_and_every_emitted_frozen_path_validate_current_ontology():
    validate_mapping_file(MAPPINGS)
    for stem, endpoint in PAYLOADS.items():
        _build(endpoint, fixture(stem))
