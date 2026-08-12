"""Positive semantic assertions over the immutable authoritative Fink/ZTF payloads."""

from collections import Counter
from itertools import count
import json
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
from alertissimo.data_layer.runtime.record_builder import build_portfolio_from_execution

ROOT = Path(__file__).parent
FIXTURES = ROOT / "fixtures/fink/ztf"
MAPPINGS = ROOT.parent / "alertissimo/data_layer/providers/fink/ztf/mappings.yaml"
DEBT = MAPPINGS.with_name("unmapped_fields.yaml")
FILES = {
    "objects": "objects_core.json",
    "conesearch": "conesearch.json",
    "latests": "latests.json",
    "anomaly": "anomaly.json",
    "sso": "sso_core.json",
    "statistics": "statistics_day.json",
}


def _payload(endpoint):
    return json.loads((FIXTURES / FILES[endpoint]).read_text(encoding="utf-8"))


def _build(endpoint, payload=None):
    ids = count()
    execution = ExecutionResult(
        payload=_payload(endpoint) if payload is None else payload,
        execution_provenance=InternalExecutionProvenance(
            InternalExecutionId(f"execution:fixture:{endpoint}"), "fink", "ztf", endpoint
        ),
    )
    return build_portfolio_from_execution(
        execution,
        mappings_path=MAPPINGS,
        internal_portfolio_id=InternalPortfolioId("portfolio:fixture"),
        record_id_factory=lambda: InternalRecordId(f"record:{next(ids)}"),
        validate_semantic_model=True,
    )


def _records(portfolio, semantic_type):
    return [record for record in portfolio.records if record.semantic_type == semantic_type]


def test_classtar_and_fink_final_classification_are_positive_products():
    portfolio = _build("objects")
    sextractor = _records(portfolio, "classification@sextractor:fink")
    fink = _records(portfolio, "classification@fink")
    assert sextractor[0].fields["assessment.star_galaxy.score"] == 1.0
    assert fink[0].fields["best.class"] == "SN candidate"
    assert not _records(_build("objects", [{"i:classtar": None}]), "classification@sextractor:fink")


def test_candid_history_reference_times_calibration_and_fixed_color():
    portfolio = _build("objects")
    detection = _records(portfolio, "detection@ztf:fink")[0]
    summary = _records(portfolio, "summary@ztf:fink")[0]
    assert detection.fields["identity.source_id"] == 1642249732315015013
    assert "identity.alert_id" not in detection.fields
    assert summary.fields["detection_count"] == 17  # native ZTF historical selection
    assert summary.fields["coverage_count"] == 431
    assert summary.fields["time.first_mjd"] == pytest.approx(59376.19172450015)
    assert summary.fields["time.last_mjd"] == pytest.approx(59396.24973380007)
    assert detection.fields["reference_image.time.first_mjd"] == pytest.approx(58203.30605300004)
    assert detection.fields["reference_image.time.last_mjd"] == pytest.approx(58322.165612999815)
    assert detection.fields["calibration.nmatches"] == 390
    assert detection.fields["calibration.color_median"] == 0.594
    assert detection.fields["calibration.color_rms"] == 0.314855
    assert summary.fields["color.g-r.diff"] == 0.744712


def test_distnr_pixels_are_not_emitted_as_angular_reference_separation():
    detection = _records(_build("objects"), "detection@ztf:fink")[0]
    assert "reference_image.nearest_source.separation.total" not in detection.fields


def test_gaia_and_panstarrs_rank_one_crossmatches_are_exact():
    portfolio = _build("objects")
    gaia = _records(portfolio, "crossmatch@gaia:fink")[0]
    ps1 = _records(portfolio, "crossmatch@panstarrs:fink")[0]
    assert gaia.fields["separation.total"] == 10.74585
    assert gaia.fields["photometry.G.mag"] == 15.864706
    assert ps1.fields["identity.object_id"] == 111471938187377161
    assert ps1.fields["separation.total"] == 10.793845
    assert ps1.fields["photometry.g.psf.mag"] == 17.85
    assert ps1.fields["classification.assessment.star_galaxy.score"] == 0.734667
    debt = yaml.safe_load(DEBT.read_text(encoding="utf-8"))["unmapped"]
    debt_refs = {next(iter(entry)) for entry in debt}
    assert {"objects#i:objectidps2", "objects#i:objectidps3"} <= debt_refs


def test_solar_system_identity_feature_vectors_and_sentinels():
    portfolio = _build("sso")
    detection = _records(portfolio, "detection@ztf:fink")[0]
    lightcurve = _records(portfolio, "lightcurve@ztf:fink")[0]
    assert detection.fields["solar_system.roid"] == 3
    assert detection.fields["solar_system.iau_name"] == "Benoitcarry"
    assert detection.fields["solar_system.iau_number"] == 8467
    assert detection.fields["solar_system.mpc_match.identity.object_id"] == "8467"
    assert "g.feature_vector" in lightcurve.fields and "r.feature_vector" in lightcurve.fields
    synthetic = _build("objects", [{"i:ssdistnr": -999.0, "i:ssmagnr": -999.0, "i:candid": -1}])
    assert not synthetic.records


def test_anomaly_emits_positive_classification_and_external_crossmatches():
    portfolio = _build("anomaly")
    assert _records(portfolio, "classification@fink")[0].fields["best.class"] == "RRLyr"
    assert _records(portfolio, "crossmatch@simbad:fink")[0].fields[
        "classification.best.class"
    ] == "RRLyr"
    assert _records(portfolio, "crossmatch@gaia:fink")[0].fields[
        "identity.object_id"
    ].startswith("Gaia DR3")


def test_statistics_emit_only_first_level_survey_records():
    portfolio = _build("statistics")
    assert not _records(portfolio, "detection@ztf:fink")
    survey = _records(portfolio, "survey@ztf:fink")
    assert len(survey) == 1
    assert dict(survey[0].fields) == {
        "exposure_count": 460,
        "field_count": 236,
        "raw_alerts": 346644,
        "science_alerts": 246843,
        "snapshot_key": "ztf_20211103",
        "time.snapshot_datetime": "1642144989032",
    }


def test_frozen_scalar_accounting_and_positive_record_counts():
    document = yaml.safe_load(MAPPINGS.read_text(encoding="utf-8"))
    mapped = {reference for refs in document["mappings"].values() for reference in refs}
    debt = {
        next(iter(entry))
        for entry in yaml.safe_load(DEBT.read_text(encoding="utf-8"))["unmapped"]
    }
    assert mapped.isdisjoint(debt)
    captured = set()
    for endpoint in FILES:
        for row in _payload(endpoint):
            captured.update(
                f"{endpoint}#{key}"
                for key, value in row.items()
                if not isinstance(value, (dict, list))
            )
    for filename in ("resolver_tns.json", "resolver_simbad.json", "resolver_ssodnet.json"):
        for row in json.loads((FIXTURES / filename).read_text(encoding="utf-8")):
            captured.update(
                f"resolver#{key}"
                for key, value in row.items()
                if not isinstance(value, (dict, list))
            )
    assert captured <= mapped | debt
    expected = {
        "objects": {"detection": 14, "summary": 14, "classification": 28, "crossmatch": 42},
        "conesearch": {"detection": 1, "summary": 1, "classification": 1},
        "latests": {"detection": 10, "summary": 10, "classification": 20, "crossmatch": 20},
        "anomaly": {"detection": 10, "summary": 10, "classification": 20, "crossmatch": 42},
        "sso": {"detection": 327, "summary": 327, "classification": 654, "crossmatch": 837, "lightcurve": 327},
        "statistics": {"survey": 1},
    }
    for endpoint, counts in expected.items():
        actual = Counter(record.semantic_type.split("@", 1)[0] for record in _build(endpoint).records)
        assert actual == counts
