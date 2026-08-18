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
from alertissimo.data_layer.runtime.record_builder import (
    build_portfolio_from_execution,
    build_portfolios_from_execution,
)
from tools.audit_payload_mapping_coverage import audit_payload

ROOT = Path(__file__).parent
FIXTURES = ROOT / "fixtures/fink/ztf"
MAPPINGS = ROOT.parent / "alertissimo/data_layer/providers/fink/ztf/mappings.yaml"
DEBT = MAPPINGS.with_name("unmapped_fields.yaml")
FILES = {
    "objects": "objects_core.json",
    "objects_withupperlim": "objects_withupperlim.json",
    "conesearch": "conesearch.json",
    "latests": "latests.json",
    "anomaly": "anomaly.json",
    "sso": "sso_core.json",
    "statistics": "statistics_day.json",
}


def _payload(endpoint):
    return json.loads((FIXTURES / FILES[endpoint]).read_text(encoding="utf-8"))


def _physical_endpoint(fixture):
    return "objects" if fixture == "objects_withupperlim" else fixture


def _build(endpoint, payload=None):
    ids = count()
    execution = ExecutionResult(
        payload=_payload(endpoint) if payload is None else payload,
        execution_provenance=InternalExecutionProvenance(
            InternalExecutionId(f"execution:fixture:{endpoint}"),
            "fink",
            "ztf",
            _physical_endpoint(endpoint),
        ),
    )
    return build_portfolio_from_execution(
        execution,
        mappings_path=MAPPINGS,
        internal_portfolio_id=InternalPortfolioId("portfolio:fixture"),
        record_id_factory=lambda: InternalRecordId(f"record:{next(ids)}"),
        validate_semantic_model=True,
    )


def _build_all(endpoint):
    execution = ExecutionResult(
        payload=_payload(endpoint),
        execution_provenance=InternalExecutionProvenance(
            InternalExecutionId(f"execution:fixture:{endpoint}"),
            "fink",
            "ztf",
            endpoint,
        ),
    )
    return build_portfolios_from_execution(
        execution, mappings_path=MAPPINGS, validate_semantic_model=True
    )


def _records(portfolio, semantic_type):
    return [record for record in portfolio.records if record.semantic_type == semantic_type]


def test_classtar_and_fink_final_classification_are_positive_products():
    portfolio = _build("objects")
    sextractor = _records(portfolio, "classification@sextractor:fink")
    fink = _records(portfolio, "classification@fink")
    assert sextractor[0].fields["assessment.star_galaxy.score"] == 1.0
    assert fink[0].fields["best.class"] == "SN candidate"
    assert not _records(
        _build("objects", [{"i:objectId": "ZTF-synthetic", "i:classtar": None}]),
        "classification@sextractor:fink",
    )


def test_current_blazar_cdf_quantile_contract_maps_value_and_omits_sentinel():
    # This optional column is supported by the current official Fink object-API
    # and Fink Science sources, but is not present in the frozen capture.
    present = _records(
        _build(
            "objects",
            [{"i:objectId": "ZTF-synthetic", "d:blazar_stats_cdf_quantile": 0.73}],
        ),
        "classification@fink",
    )[0]
    assert present.fields["assessment.blazar_extreme_state_cdf_quantile.value"] == 0.73
    assert not _records(
        _build(
            "objects",
            [{"i:objectId": "ZTF-synthetic", "d:blazar_stats_cdf_quantile": -1.0}],
        ),
        "classification@fink",
    )


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
    assert detection.fields["reference_image.time.first_mjd"] == pytest.approx(
        58203.30605300004
    )
    assert detection.fields["reference_image.time.last_mjd"] == pytest.approx(
        58322.165612999815
    )
    assert detection.fields["calibration.nmatches"] == 390
    assert detection.fields["calibration.color_median"] == 0.594
    assert detection.fields["calibration.color_rms"] == 0.314855
    lightcurve = _records(portfolio, "lightcurve@fink")[0]
    color_points = lightcurve.fields["color_points"]
    assert any(
        point.get("color.g-r.diff") == pytest.approx(0.744712)
        for point in color_points
    )


def test_distnr_pixels_are_not_emitted_as_angular_reference_separation():
    detection = _records(_build("objects"), "detection@ztf:fink")[0]
    assert "reference_image.nearest_source.separation.total" not in detection.fields


def test_gaia_and_panstarrs_rank_one_crossmatches_are_exact():
    portfolio = _build("objects")
    gaia = _records(portfolio, "crossmatch@gaia_dr1:fink")[0]
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
    lightcurve = _records(portfolio, "lightcurve@fink")[0]
    assert detection.fields["solar_system.roid"] == 3
    assert detection.fields["solar_system.iau_name"] == "Benoitcarry"
    assert detection.fields["solar_system.iau_number"] == 8467
    assert detection.fields["solar_system.mpc_match.identity.object_id"] == "8467"
    feature_points = lightcurve.fields["feature_vector_points"]
    assert any("g.value" in point for point in feature_points)
    assert any("r.value" in point for point in feature_points)
    assert all("time.mjd" in point for point in feature_points)
    synthetic = _build(
        "objects",
        [
            {
                "i:objectId": "ZTF-synthetic",
                "i:ssdistnr": -999.0,
                "i:ssmagnr": -999.0,
                "i:candid": -1,
            }
        ],
    )
    assert not _records(synthetic, "detection@ztf:fink")


def test_anomaly_splits_gaia_dr1_and_dr3_and_rejects_default_astrometry():
    portfolio = next(
        p
        for p in _build_all("anomaly")
        if _records(p, "classification@fink")
        and _records(p, "classification@fink")[0].fields.get("best.class") == "RRLyr"
    )
    assert _records(portfolio, "classification@fink")[0].fields["best.class"] == "RRLyr"
    assert _records(portfolio, "crossmatch@simbad:fink")[0].fields[
        "classification.best.class"
    ] == "RRLyr"
    dr1 = _records(portfolio, "crossmatch@gaia_dr1:fink")[0]
    dr3 = _records(portfolio, "crossmatch@gaia_dr3:fink")[0]
    assert dr1.fields["separation.total"] == pytest.approx(0.24318255)
    assert dr1.fields["photometry.G.mag"] == pytest.approx(15.835548)
    assert dr3.fields["identity.object_id"].startswith("Gaia DR3")
    assert "identity.object_id" not in dr1.fields
    assert "separation.total" not in dr3.fields
    assert not any(
        "astrometric_solution.parallax" in record.fields for record in portfolio.records
    )
    default = _build(
        "anomaly",
        [
            {
                "i:objectId": "ZTF-synthetic",
                "d:DR3Name": "Unknown",
                "d:Plx": 0.0,
                "d:e_Plx": 0.0,
            }
        ],
    )
    assert not _records(default, "crossmatch@gaia_dr3:fink")


def test_gaia_catalog_queries_and_variability_sentinels_stay_separate():
    positive = _build(
        "anomaly",
        [
            {
                "i:objectId": "ZTF-synthetic",
                "d:DR3Name": "Gaia DR3 123",
                "d:gaiaVarFlag": 1,
                "d:gaiaClass": "RR",
            }
        ],
    )
    dr3 = _records(positive, "crossmatch@gaia_dr3:fink")[0]
    variability = _records(positive, "crossmatch@gaia_variability:fink")[0]
    assert dr3.fields == {
        "identity.object_id": "Gaia DR3 123",
        "classification.assessment.variability.flag": True,
    }
    assert variability.fields["classification.assessment.variability.class"] == "RR"

    unavailable = _build(
        "anomaly",
        [{"i:objectId": "ZTF-synthetic", "d:DR3Name": "Unknown", "d:gaiaVarFlag": 0}],
    )
    assert not _records(unavailable, "crossmatch@gaia_dr3:fink")
    frozen = _build("sso")
    assert not any(
        record.fields.get("classification.assessment.variability.flag") is False
        for record in frozen.records
    )


def test_nearest_bright_gaia_dr1_selection_is_structural_debt():
    document = yaml.safe_load(MAPPINGS.read_text(encoding="utf-8"))
    assert not any(
        path.startswith("crossmatch@gaia_dr1_bright") for path in document["mappings"]
    )


def test_upper_limit_fixture_preserves_limit_semantics_without_measurements():
    payload = _payload("objects_withupperlim")
    tags = Counter(row["d:tag"] for row in payload)
    assert len(payload) == 33
    assert tags == {"valid": 14, "upperlim": 19}
    portfolio = _build("objects_withupperlim")
    detections = _records(portfolio, "detection@ztf:fink")
    assert len(detections) == 33
    for raw, record in zip(payload, detections, strict=True):
        band = {1: "g", 2: "r", 3: "i", "1": "g", "2": "r", "3": "i"}[
            raw["i:fid"]
        ]
        if raw["d:tag"] == "upperlim":
            assert record.fields[f"photometry.{band}.upper_limit"] is True
            assert record.fields[f"photometry.{band}.limit.mag"] == raw["i:diffmaglim"]
            for field in (
                "psf.mag",
                "psf.mag.error",
                "aperture.mag",
                "aperture.large.mag",
            ):
                assert f"photometry.{band}.{field}" not in record.fields
        else:
            # Policy A: an upstream-valid measured detection explicitly is not an upper limit.
            assert record.fields[f"photometry.{band}.upper_limit"] is False
    bad = _records(
        _build(
            "objects",
            [{"i:objectId": "ZTF-synthetic", "i:fid": "1", "d:tag": "badquality"}],
        ),
        "detection@ztf:fink",
    )
    assert not bad  # badquality is neither a valid detection nor an upper limit


def test_tns_alert_field_is_catalog_type_not_identity():
    record = _records(
        _build("objects", [{"i:objectId": "ZTF-synthetic", "d:tns": "SN Ia"}]),
        "crossmatch@tns:fink",
    )[0]
    assert record.fields["classification.best.class"] == "SN Ia"
    assert "identity.object_id" not in record.fields


def test_object_and_cone_final_classification_converge():
    assert (
        _records(_build("objects"), "classification@fink")[0].fields["best.class"]
        == "SN candidate"
    )
    assert (
        _records(_build("conesearch"), "classification@fink")[0].fields["best.class"]
        == "SN candidate"
    )


def test_fast_transient_fields_are_explicit_structural_debt_until_rate_point_collection():
    document = yaml.safe_load(MAPPINGS.read_text(encoding="utf-8"))
    mapped = {reference for refs in document["mappings"].values() for reference in refs}
    debt = {
        next(iter(entry))
        for entry in yaml.safe_load(DEBT.read_text(encoding="utf-8"))["unmapped"]
    }
    expected = {
        f"{payload}#{field}"
        for payload in ("objects", "sso", "latests", "anomaly")
        for field in ("d:mag_rate", "d:sigma_rate", "d:lower_rate", "d:upper_rate")
    }
    expected |= {
        f"{payload}#{field}"
        for payload in ("sso", "latests", "anomaly")
        for field in ("d:delta_time", "d:from_upper")
    }
    assert expected <= debt
    assert mapped.isdisjoint(expected)


def test_blazar_extreme_state_assessments_are_explicit_and_suppress_minus_one():
    positive = _records(
        _build(
            "anomaly",
            [
                {
                    "i:objectId": "ZTF-synthetic",
                    "d:blazar_stats_instantness_low": 0.1,
                    "d:blazar_stats_robustness_low": 0.2,
                    "d:blazar_stats_instantness_high": 0.3,
                    "d:blazar_stats_robustness_high": 0.4,
                }
            ],
        ),
        "classification@fink",
    )[0]
    assert dict(positive.fields) == {
        "assessment.blazar_extreme_state_instantness_low.value": 0.1,
        "assessment.blazar_extreme_state_robustness_low.value": 0.2,
        "assessment.blazar_extreme_state_instantness_high.value": 0.3,
        "assessment.blazar_extreme_state_robustness_high.value": 0.4,
    }
    unavailable = _build(
        "anomaly",
        [
            {
                "i:objectId": "ZTF-synthetic",
                "d:blazar_stats_instantness_low": -1,
                "d:blazar_stats_robustness_low": -1.0,
            }
        ],
    )
    assert not _records(unavailable, "classification@fink")


def test_frozen_service_failures_are_never_scientific_values():
    payload = _payload("sso")
    observed = {
        value
        for row in payload
        for value in row.values()
        if isinstance(value, str) and value in {"Fail", "Fail 500", "Fail 503"}
    }
    assert observed == {"Fail", "Fail 500", "Fail 503"}
    portfolio = _build("sso")
    assert not any(
        value in observed for record in portfolio.records for value in record.fields.values()
    )


def test_statistics_are_mapped_but_not_object_portfolios():
    document = yaml.safe_load(MAPPINGS.read_text(encoding="utf-8"))
    assert document["payloads"]["statistics"]["object_partition"] == {"mode": "none"}
    assert _build_all("statistics") == ()
    report = audit_payload(
        _payload("statistics"), broker="fink", origin="ztf", endpoint="statistics"
    )
    assert "Portfolios: 0" in report
    assert "Portfolio records: 0" in report
    assert any(
        ref.startswith("statistics#")
        for refs in document["mappings"].values()
        for ref in refs
    )


def test_authoritative_multi_object_cardinalities_and_provenance():
    anomaly = _build_all("anomaly")
    assert len(anomaly) == 10
    anomaly_ids = [
        {
            r.fields["identity.object_id"]
            for r in p.records
            if r.semantic_type == "summary@ztf:fink"
        }
        for p in anomaly
    ]
    assert all(len(ids) == 1 for ids in anomaly_ids) and len(
        {next(iter(ids)) for ids in anomaly_ids}
    ) == 10
    assert all(
        p.executions[0].internal_execution_id
        == InternalExecutionId("execution:fixture:anomaly")
        for p in anomaly
    )

    latest = _build_all("latests")
    raw_counts = Counter(row["i:objectId"] for row in _payload("latests"))
    assert len(latest) == 7
    actual = {
        next(
            r.fields["identity.object_id"]
            for r in p.records
            if r.semantic_type == "summary@ztf:fink"
        ): len(_records(p, "detection@ztf:fink"))
        for p in latest
    }
    assert actual == raw_counts
    assert all(
        p.executions[0].internal_execution_id
        == InternalExecutionId("execution:fixture:latests")
        for p in latest
    )
    for portfolios in (anomaly, latest):
        assert len({p.internal_portfolio_id for p in portfolios}) == len(portfolios)


def test_authoritative_sso_is_one_solar_system_object():
    rows = _payload("sso")
    assert len(rows) == 327 and {row["sso_number"] for row in rows} == {8467}
    (portfolio,) = _build_all("sso")
    assert len(_records(portfolio, "detection@ztf:fink")) == 327
    assert portfolio.executions[0].internal_execution_id == InternalExecutionId(
        "execution:fixture:sso"
    )


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
                f"{_physical_endpoint(endpoint)}#{key}"
                for key, value in row.items()
                if not isinstance(value, (dict, list))
            )
    for filename in (
        "resolver_tns.json",
        "resolver_simbad.json",
        "resolver_ssodnet.json",
    ):
        for row in json.loads((FIXTURES / filename).read_text(encoding="utf-8")):
            captured.update(
                f"resolver#{key}"
                for key, value in row.items()
                if not isinstance(value, (dict, list))
            )
    assert captured <= mapped | debt
    assert not (captured - mapped - debt)
