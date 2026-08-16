"""Authoritative tests for the frozen 2026-08-12 Fink/Rubin capture."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import statistics
from itertools import count
from pathlib import Path

import pytest
import yaml

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
    InternalPortfolioId,
    InternalRecordId,
)
from alertissimo.data_layer.runtime.record_builder import build_portfolio_from_execution, build_portfolios_from_execution
from alertissimo.data_layer.runtime.mapping_schema import validate_mapping_file

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests/fixtures/fink/lsst"
MAPPINGS = ROOT / "alertissimo/data_layer/providers/fink/lsst/mappings.yaml"
UNMAPPED = MAPPINGS.with_name("unmapped_fields.yaml")
EXPECTED_SHA256 = {
    "objects": "66106181ca8f8d3d16cd83f5bcdcb3afb296509fdcae7cf9f829c6cdfac8f785",
    "sources": "bddb4675604090312b7283254ea32980986f3098222653b75bb9809c160d939a",
    "fp": "9eef7a54465ea4f07ee40b033a8cb1eb1c4c37d82a124c72bf699c49f327bb55",
    "conesearch": "eb06630fea13ef5fb4ed8088ad2f3c0f3fadff0532e468826063ec4dd41d8725",
}


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def registry():
    return yaml.safe_load(MAPPINGS.read_text(encoding="utf-8"))


def test_fixture_bytes_and_primary_evidence():
    for name, digest in EXPECTED_SHA256.items():
        assert hashlib.sha256((FIXTURES / f"{name}.json").read_bytes()).hexdigest() == digest
    objects, sources, forced, cone = map(fixture, ("objects", "sources", "fp", "conesearch"))
    assert [len(x) for x in (objects, sources, forced, cone)] == [1, 16, 20, 1]
    assert [len({key for row in x for key in row}) for x in (objects, sources, forced, cone)] == [91, 135, 15, 10]
    obj = objects[0]
    assert obj["r:diaObjectId"] == 170587117485817955 and isinstance(obj["r:diaObjectId"], int)
    assert (obj["r:nDiaSources"], obj["r:firstDiaSourceMjdTai"], obj["r:lastDiaSourceMjdTai"]) == (16, None, None)
    assert obj["f:firstDiaSourceMjdTaiFink"] == 61217.421180064
    assert obj["r:validityStartMjdTai"] == 61235.4210556968
    assert (obj["r:observation_reason"], obj["r:target_name"]) == ("ddf_edfs_b", "ddf_edfs_b, lowdust")
    assert all(set(row) == set(sources[0]) for row in sources)
    assert all(set(row) == set(forced[0]) for row in forced)


def test_sources_and_forced_photometry_partition_on_prefixed_object_id():
    for endpoint, expected_records in (("sources", 16), ("fp", 20)):
        rows = fixture(endpoint)
        assert all("r:diaObjectId" in row and "diaObjectId" not in row for row in rows)
        execution = ExecutionResult(payload=rows, execution_provenance=InternalExecutionProvenance(
            InternalExecutionId(f"execution:fixture:{endpoint}"), "fink", "lsst", endpoint
        ))
        portfolios = build_portfolios_from_execution(execution, mappings_path=MAPPINGS, validate_semantic_model=True)
        assert len(portfolios) == 1
        portfolio = portfolios[0]
        assert portfolio.executions == (execution.execution_provenance,)
        assert len([r for r in portfolio.records if r.semantic_type == "detection@lsst:fink"]) == expected_records
        assert {r.fields["identity.object_id"] for r in portfolio.records if "identity.object_id" in r.fields} == {170587117485817955}


def test_source_schema_versions_types_sentinels_and_mixed_history():
    rows = fixture("sources")
    assert all(row["r:diaObjectId"] == 170587117485817955 for row in rows)
    ids = [row["r:diaSourceId"] for row in rows]
    assert len(set(ids)) == 16 and all(isinstance(value, int) for value in ids)
    assert {band: sum(row["r:band"] == band for row in rows) for band in "griz"} == {"g": 5, "r": 5, "i": 5, "z": 1}
    earliest, latest = min(rows, key=lambda x: x["r:midpointMjdTai"]), max(rows, key=lambda x: x["r:midpointMjdTai"])
    assert (earliest["r:diaSourceId"], earliest["r:midpointMjdTai"]) == (170587117485817955, 61217.421180064)
    assert (latest["r:diaSourceId"], latest["r:midpointMjdTai"]) == (170666304474710039, 61235.4191836794)
    assert latest["r:diaSourceId"] != latest["r:diaObjectId"]
    for key, value in (("r:parentDiaSourceId", 0), ("r:ssObjectId", 0), ("r:timeWithdrawnMjdTai", None), ("r:psfLnL", None), ("r:exposureTime", None)):
        assert all(row[key] == value for row in rows)
    boolean_fields = {"r:isNegative", "r:psfFlux_flag", "r:psfFlux_flag_edge", "r:psfFlux_flag_noGoodPixels", "r:apFlux_flag", "r:apFlux_flag_apertureTruncated", "r:centroid_flag", "r:glint_trail", "r:isDipole", "r:dipoleFitAttempted", "r:shape_flag", "r:pixelFlags", "r:forced_PsfFlux_flag", "r:forced_PsfFlux_flag_edge", "r:forced_PsfFlux_flag_noGoodPixels", "r:trail_flag_edge"}
    assert all(type(row[field]) is bool for row in rows for field in boolean_fields)
    assert sum(row["r:trail_flag"] == "nan" for row in rows) == 13
    assert sum(row["r:trail_flag"] is False for row in rows) == 3
    assert {value: [row["r:trailAlgorithm"] for row in rows].count(value) for value in (None, 1)} == {None: 13, 1: 3}
    assert {value: [row["r:reliabilityVersion"] for row in rows].count(value) for value in ("nan", "0.3")} == {"nan": 13, "0.3": 3}
    assert {row["f:lsst_schema_version"] for row in rows} == {"lsst.v10_0", "lsst.v11_0", "lsst.v11_1"}


def test_forced_rows_are_distinct_atomic_measurements():
    sources, forced = fixture("sources"), fixture("fp")
    key = lambda row: (row["r:midpointMjdTai"], row["r:visit"], row["r:detector"])
    source_by_key, forced_by_key = ({key(row): row for row in rows} for rows in (sources, forced))
    common = source_by_key.keys() & forced_by_key.keys()
    assert (len(common), len(source_by_key.keys() - common), len(forced_by_key.keys() - common)) == (12, 4, 8)
    assert len({row["r:diaSourceId"] for row in sources}) == 16
    assert len({row["r:diaForcedSourceId"] for row in forced}) == 20
    assert all(isinstance(row["r:diaForcedSourceId"], int) for row in forced)
    assert any(source_by_key[k]["r:diaSourceId"] != forced_by_key[k]["r:diaForcedSourceId"] and source_by_key[k]["r:psfFlux"] != forced_by_key[k]["r:psfFlux"] for k in common)
    assert all(row["r:timeWithdrawnMjdTai"] is None for row in forced)


def test_object_psf_aggregates_are_scientifically_reproduced():
    obj, rows = fixture("objects")[0], fixture("sources")
    for band in "griz":
        selected = [row for row in rows if row["r:band"] == band]
        flux = [row["r:psfFlux"] for row in selected]
        errors = [row["r:psfFluxErr"] for row in selected]
        weights = [1 / error**2 for error in errors]
        prefix = f"r:{band}_psfFlux"
        assert obj[prefix + "Ndata"] == len(selected)
        assert obj[prefix + "Min"] == min(flux)
        assert obj[prefix + "Max"] == max(flux)
        assert obj[prefix + "ErrMean"] == pytest.approx(statistics.fmean(errors), rel=2e-7)
        assert obj[prefix + "Mean"] == pytest.approx(sum(f * w for f, w in zip(flux, weights)) / sum(weights), rel=2e-7)
        assert obj[prefix + "MeanErr"] == pytest.approx(math.sqrt(1 / sum(weights)), rel=2e-7)
        if len(flux) == 1:
            assert obj[prefix + "Sigma"] is None
        else:
            assert obj[prefix + "Sigma"] == pytest.approx(statistics.stdev(flux), rel=2e-7)
    assert all(fixture("objects")[0][f"r:{band}_fpFluxMean"] is None for band in "ugrizy")


def test_core_mapping_contract_and_debt_are_disjoint():
    document = registry(); mappings = document["mappings"]
    assert mappings["summary@lsst:fink.time.snapshot_mjd"] == ["objects#r:validityStartMjdTai", "conesearch#r:validityStartMjdTai"]
    forbidden = {"summary@lsst:fink.time.first_mjd_fink", "detection@lsst:fink.image_metrics.is_negative"}
    forbidden |= {path for path in mappings if any(token in path for token in ("position.pixel.", ".psf.log_likelihood", ".centroid.flag", ".shape.flags.", ".pixel_flags.failed", ".dipole.fit_ndata", ".trail.fit_ndata", ".trail.flags.edge"))}
    assert not forbidden & mappings.keys()
    expected = {"detection@lsst:fink.position.image_x", "detection@lsst:fink.position.image_x_error", "detection@lsst:fink.position.image_y", "detection@lsst:fink.position.image_y_error", "detection@lsst:fink.time.exposure", "detection@lsst:fink.photometry.{filter}.psf.fit_log_likelihood", "detection@lsst:fink.image_metrics.centroid_flag", "detection@lsst:fink.image_metrics.trail.is_glint", "detection@lsst:fink.image_metrics.shape.flag", "detection@lsst:fink.image_metrics.pixel_flags.any", "detection@lsst:fink.image_metrics.dipole.ndata", "detection@lsst:fink.image_metrics.trail.ndata", "detection@lsst:fink.image_metrics.trail.flag_edge"}
    assert expected <= mappings.keys()
    assert document["transforms"]["detection@lsst:fink.image_metrics.is_positive"]["sources#r:isNegative"] == {"type": "boolean_not"}
    assert not any(path.startswith("lightcurve@lsst:fink") for path in mappings)
    assert "fp#r:diaForcedSourceId" in mappings["detection@lsst:fink.identity.source_id"]
    mapped = {ref for refs in mappings.values() for ref in refs}
    debt = {next(iter(entry)) for entry in yaml.safe_load(UNMAPPED.read_text())["unmapped"]}
    assert mapped.isdisjoint(debt)


def test_all_authoritative_scalar_refs_are_accounted():
    document = registry(); mapped = {ref for refs in document["mappings"].values() for ref in refs}
    debt = {next(iter(entry)) for entry in yaml.safe_load(UNMAPPED.read_text())["unmapped"]}
    for endpoint in ("objects", "sources", "fp", "conesearch"):
        observed = {f"{endpoint}#{key}" for row in fixture(endpoint) for key in row}
        assert observed <= mapped | debt, sorted(observed - mapped - debt)


def test_first_mjd_native_precedence_and_documented_fallback(tmp_path):
    path = "summary@lsst:fink.time.first_mjd"
    row = fixture("objects")[0]
    fields = dict(_build_filtered(tmp_path, "objects", [row], [path]).records[0].fields)
    assert fields["time.first_mjd"] == 61217.421180064

    native = copy.deepcopy(row)
    native["r:firstDiaSourceMjdTai"] = 61200.25
    native["f:firstDiaSourceMjdTaiFink"] = 61199.5
    fields = dict(_build_filtered(tmp_path, "objects", [native], [path]).records[0].fields)
    assert fields["time.first_mjd"] == 61200.25


def test_cone_separation_is_scaled_to_arcseconds(tmp_path):
    row = fixture("conesearch")[0]
    portfolio = _build_filtered(
        tmp_path, "conesearch", [row],
        ["detection@lsst:fink.separation.from_search_center"],
    )
    assert portfolio.records[0].fields["separation.from_search_center"] == pytest.approx(
        0.13504932
    )


@pytest.mark.parametrize("endpoint", ("sources", "conesearch"))
def test_optional_ss_object_id_suppresses_zero_and_preserves_integer(tmp_path, endpoint):
    row = copy.deepcopy(fixture(endpoint)[0])
    path = "detection@lsst:fink.solar_system.identity.object_id"
    paths = [path, "detection@lsst:fink.identity.source_id"]
    fields = dict(_build_filtered(tmp_path, endpoint, [row], paths).records[0].fields)
    assert "solar_system.identity.object_id" not in fields
    row["r:ssObjectId"] = 123456789
    fields = dict(_build_filtered(tmp_path, endpoint, [row], paths).records[0].fields)
    assert fields["solar_system.identity.object_id"] == 123456789
    assert type(fields["solar_system.identity.object_id"]) is int


def _build_filtered(tmp_path, endpoint, payload, semantic_paths):
    source = registry()
    mappings = {path: [ref for ref in source["mappings"][path] if ref.startswith(endpoint + "#")] for path in semantic_paths}
    mappings = {path: refs for path, refs in mappings.items() if refs}
    document = {"broker": "fink", "origin": "lsst", "payloads": {endpoint: source["payloads"][endpoint]}, "mappings": mappings}
    transforms = {path: {ref: spec for ref, spec in source.get("transforms", {}).get(path, {}).items() if ref.startswith(endpoint + "#")} for path in mappings}
    transforms = {path: refs for path, refs in transforms.items() if refs}
    if transforms: document["transforms"] = transforms
    path = tmp_path / f"{endpoint}.yaml"; path.write_text(yaml.safe_dump(document, sort_keys=False))
    validate_mapping_file(path)
    ids = count()
    result = ExecutionResult(payload=payload, execution_provenance=InternalExecutionProvenance(internal_execution_id=InternalExecutionId("execution:fixture"), broker="fink", origin="lsst", endpoint=endpoint))
    return build_portfolio_from_execution(result, mappings_path=path, internal_portfolio_id=InternalPortfolioId("portfolio:fixture"), record_id_factory=lambda: InternalRecordId(f"record:{next(ids)}"), validate_semantic_model=True)


def test_real_source_and_boolean_not_end_to_end(tmp_path):
    paths = [path for path in registry()["mappings"] if path.startswith("detection@lsst:fink.") and any(ref.startswith("sources#") for ref in registry()["mappings"][path]) and not any(token in path for token in ("solar_system", "classification", "crossmatch"))]
    row = next(row for row in fixture("sources") if row["r:diaSourceId"] != row["r:diaObjectId"])
    portfolio = _build_filtered(tmp_path, "sources", [row, {**copy.deepcopy(row), "r:isNegative": True}], paths)
    records = [record for record in portfolio.records if record.semantic_type == "detection@lsst:fink"]
    assert len(records) == 2
    first, second = map(lambda record: dict(record.fields), records)
    band = row["r:band"]
    exact = {"identity.object_id": "r:diaObjectId", "identity.source_id": "r:diaSourceId", "identity.visit_id": "r:visit", "identity.detector_id": "r:detector", "time.mjd": "r:midpointMjdTai", "position.ra": "r:ra", "position.dec": "r:dec", "position.ra_error": "r:raErr", "position.dec_error": "r:decErr", "position.ra_dec_covariance": "r:ra_dec_Cov", "position.image_x": "r:x", "position.image_x_error": "r:xErr", "position.image_y": "r:y", "position.image_y_error": "r:yErr", f"photometry.{band}.psf.flux": "r:psfFlux", f"photometry.{band}.psf.flux.error": "r:psfFluxErr", f"forced_photometry.{band}.psf.flux": "r:scienceFlux", f"forced_photometry.{band}.psf.flux.error": "r:scienceFluxErr", f"forced_photometry.{band}.psf.flags.failed": "r:forced_PsfFlux_flag", f"forced_photometry.{band}.psf.flags.edge": "r:forced_PsfFlux_flag_edge", f"forced_photometry.{band}.psf.flags.no_good_pixels": "r:forced_PsfFlux_flag_noGoodPixels", f"reference_image.forced_photometry.{band}.psf.flux": "r:templateFlux", f"reference_image.forced_photometry.{band}.psf.flux.error": "r:templateFluxErr", f"photometry.{band}.psf.fit_chi2": "r:psfChi2", f"photometry.{band}.psf.fit_ndata": "r:psfNdata", f"photometry.{band}.aperture.flux": "r:apFlux", f"photometry.{band}.aperture.flux.error": "r:apFluxErr", "quality.signal_to_noise": "r:snr", "quality.reliability": "r:reliability", "image_metrics.centroid_flag": "r:centroid_flag", "image_metrics.dipole.ndata": "r:dipoleNdata", "image_metrics.trail.ndata": "r:trailNdata", "image_metrics.trail.flag_edge": "r:trail_flag_edge"}
    assert all(first[semantic] == row[raw] for semantic, raw in exact.items())
    assert first["image_metrics.is_positive"] is True and second["image_metrics.is_positive"] is False


def test_lifecycle_reliability_and_trail_debt_converges_end_to_end(tmp_path):
    paths = [
        "detection@lsst:fink.time.processed_mjd",
        "detection@lsst:fink.time.invalidated_mjd",
        "detection@lsst:fink.quality.reliability.version",
        "detection@lsst:fink.image_metrics.trail.algorithm",
        "detection@lsst:fink.image_metrics.trail.fit_failed",
    ]
    rows = fixture("sources")
    recent = next(row for row in rows if row["r:reliabilityVersion"] == "0.3")
    historical = next(row for row in rows if row["r:reliabilityVersion"] == "nan")
    portfolio = _build_filtered(tmp_path, "sources", [recent, historical], paths)
    recent_fields, historical_fields = (dict(record.fields) for record in portfolio.records)
    assert recent_fields["time.processed_mjd"] == recent["r:timeProcessedMjdTai"]
    assert recent_fields["quality.reliability.version"] == "0.3"
    assert recent_fields["image_metrics.trail.algorithm"] == "sdss_shape"
    assert recent_fields["image_metrics.trail.fit_failed"] is False
    assert recent_fields["time.invalidated_mjd"] is None
    assert "quality.reliability.version" not in historical_fields
    assert "image_metrics.trail.algorithm" not in historical_fields
    assert "image_metrics.trail.fit_failed" not in historical_fields
    assert historical_fields["time.invalidated_mjd"] is None


def test_fp_endpoint_emits_twenty_detection_records(tmp_path):
    paths = [path for path, refs in registry()["mappings"].items() if any(ref.startswith("fp#") for ref in refs)]
    portfolio = _build_filtered(tmp_path, "fp", fixture("fp"), paths)
    assert len(portfolio.records) == 20
    assert {record.semantic_type for record in portfolio.records} == {"detection@lsst:fink"}
    row, fields = fixture("fp")[0], dict(portfolio.records[0].fields); band = row["r:band"]
    expected = {"identity.object_id": row["r:diaObjectId"], "identity.source_id": row["r:diaForcedSourceId"], "identity.visit_id": row["r:visit"], "identity.detector_id": row["r:detector"], "time.mjd": row["r:midpointMjdTai"], "position.ra": row["r:ra"], "position.dec": row["r:dec"], f"forced_photometry.{band}.psf.flux": row["r:psfFlux"], f"forced_photometry.{band}.psf.flux.error": row["r:psfFluxErr"]}
    assert {key: fields[key] for key in expected} == expected


def test_rubin_native_destinations_converge_with_alerce_and_antares():
    providers = {name: yaml.safe_load((ROOT / f"alertissimo/data_layer/providers/{name}/lsst/mappings.yaml").read_text())["mappings"] for name in ("fink", "alerce", "antares")}
    suffixes = ("identity.object_id", "identity.source_id", "identity.visit_id", "identity.detector_id", "time.mjd", "position.ra", "position.dec", "position.ra_error", "position.dec_error", "position.ra_dec_covariance", "position.image_x", "position.image_x_error", "position.image_y", "position.image_y_error", "photometry.{filter}.psf.flux", "photometry.{filter}.psf.flux.error", "photometry.{filter}.psf.fit_chi2", "photometry.{filter}.psf.fit_ndata", "photometry.{filter}.aperture.flux", "photometry.{filter}.aperture.flux.error", "quality.signal_to_noise", "quality.reliability", "image_metrics.bbox_size", "image_metrics.centroid_flag", "image_metrics.dipole.ndata", "image_metrics.trail.ndata", "image_metrics.trail.is_glint", "image_metrics.is_positive")
    for suffix in suffixes:
        assert all(any(path.endswith(suffix) for path in mappings) for mappings in providers.values()), suffix
