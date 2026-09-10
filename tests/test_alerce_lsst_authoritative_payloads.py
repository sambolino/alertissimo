"""Authoritative ALeRCE 2.3.1 multisurvey LSST payload audit."""
from __future__ import annotations
from itertools import count
import json
from pathlib import Path
import pytest
import yaml
from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance, InternalPortfolioId, InternalRecordId
from alertissimo.data_layer.runtime.record_builder import build_portfolio_from_execution
from tools.audit_payload_mapping_coverage import audit_payload

FIXTURES = Path(__file__).parent / "fixtures" / "alerce" / "lsst"
MAPPINGS = Path(__file__).parents[1] / "alertissimo/data_layer/providers/alerce/lsst/mappings.yaml"
ENDPOINTS = ("query_objects", "query_object", "query_detections", "query_non_detections", "query_forced_photometry", "query_lightcurve", "query_probabilities")

def fixture(endpoint): return json.loads((FIXTURES / f"{endpoint}.json").read_text())
def build(endpoint, payload):
    ids=count()
    return build_portfolio_from_execution(ExecutionResult(payload=payload, execution_provenance=InternalExecutionProvenance(internal_execution_id=InternalExecutionId(f"execution:fixture:{endpoint}"), broker="alerce", origin="lsst", endpoint=endpoint)), mappings_path=MAPPINGS, internal_portfolio_id=InternalPortfolioId("portfolio:fixture"), record_id_factory=lambda: InternalRecordId(f"record:{next(ids)}"), validate_semantic_model=True)

@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_every_captured_endpoint_has_zero_unaccounted_leaves(endpoint):
    report=audit_payload(fixture(endpoint), broker="alerce", origin="lsst", endpoint=endpoint)
    assert "Unaccounted leaves:\n  (none)" in report
    assert "Unaccounted leaves: 0" in report

def test_authoritative_shapes_and_forced_count_discrepancy():
    obj=fixture("query_object"); lc=fixture("query_lightcurve")
    assert (obj["n_det"],obj["n_forced"],obj["n_non_det"]) == (16,23,0)
    assert len(fixture("query_objects")) == 2
    assert len(fixture("query_detections")) == 16
    assert len(fixture("query_forced_photometry")) == 10
    assert fixture("query_non_detections") == []
    assert tuple(map(len,(lc["detections"],lc["non_detections"],lc["forced_photometry"]))) == (16,0,10)
    assert len(fixture("query_probabilities")) == 10

def test_query_object_builds_only_the_clean_summary():
    p=build("query_object",fixture("query_object")); assert len(p.records)==1
    r=p.records[0]; assert r.semantic_type=="summary@lsst:alerce"
    assert dict(r.fields)=={"identity.object_id":170587117485817955,"position.ra":62.45763123249455,"position.dec":-48.481492749718534,"position.ra_error":4.146258333646398e-06,"position.dec_error":3.97436696170811e-06,"time.first_mjd":61217.42118006405,"time.last_mjd":61235.41918367943,"time.timespan_days":17.998003615379275,"detection_count":16}
    assert not any(x.semantic_type.startswith("classification@") for x in p.records); assert p.edges==()

def test_query_objects_same_oid_preserves_object_position_classifier_records_and_row_association():
    rows = fixture("query_objects")
    assert len({row["oid"] for row in rows}) == 1
    assert {row["ranking"] for row in rows} == {1}

    portfolio = build("query_objects", rows)
    classifications = [
        record for record in portfolio.records
        if record.semantic_type.startswith("classification@")
    ]
    summaries = [
        record for record in portfolio.records
        if record.semantic_type == "summary@lsst:alerce"
    ]
    assert {record.semantic_type for record in classifications} == {
        "classification@stamp_classifier_rubin_beta_20260421:alerce",
        "classification@stamp_classifier_rubin_beta:alerce",
    }
    assert {record.fields["best.class"] for record in classifications} == {"SN", "AGN"}
    assert len(summaries) == 2
    assert all(
        dict(record.fields) == {
            "identity.object_id": 170587117485817955,
            "position.ra": 62.45763123249455,
            "position.dec": -48.481492749718534,
        }
        for record in summaries
    )
    assert not any(
        field.startswith("classification.")
        for record in summaries
        for field in record.fields
    )
    for payload_index in range(len(rows)):
        row_records = [
            record for record in portfolio.records
            if record.internal_source.payload_key == "query_objects"
            and record.internal_source.payload_index == payload_index
        ]
        assert {record.semantic_type.split("@", 1)[0] for record in row_records} == {
            "summary", "classification"
        }
    assert portfolio.edges == ()

def test_real_detection_maps_safe_identity_astrometry_photometry_and_provenance():
    row=fixture("query_detections")[0]; f=dict(build("query_detections",[row]).records[0].fields)
    assert f["identity.object_id"]==170587117485817955 and f["identity.source_id"]==170587117485817955
    assert f["time.mjd"]==61217.42118006405 and f["position.ra"]==62.45761131986638 and f["position.dec"]==-48.48149141631282
    assert f["photometry.g.psf.flux"]==2665.0413 and f["photometry.g.psf.flux.error"]==139.14035
    assert f["photometry.g.aperture.flux"]==3038.6384 and f["quality.signal_to_noise"]==18.848682
    assert f["identity.visit_id"]==2026062500651 and f["identity.detector_id"]==160 and f["provenance.producer.name"]=="lsst"
    assert f["image_metrics.is_positive"] is True
    assert f["time.processed_mjd"] == row["timeProcessedMjdTai"] == 61217.42270213738
    assert f["time.invalidated_mjd"] is None
    assert f["forced_photometry.g.psf.flux"] == row["scienceFlux"] == 4041.9963
    assert f["forced_photometry.g.psf.flux.error"] == row["scienceFluxErr"] == 136.00594
    assert f["reference_image.forced_photometry.g.psf.flux"] == row["templateFlux"] == 1294.5573
    assert f["reference_image.forced_photometry.g.psf.flux.error"] == row["templateFluxErr"] == 37.687428
    assert f["forced_photometry.g.psf.flags.failed"] is False
    assert f["forced_photometry.g.psf.flags.edge"] is False
    assert f["forced_photometry.g.psf.flags.no_good_pixels"] is False

def test_later_detection_proves_object_and_measurement_id_are_distinct_integers():
    row = fixture("query_detections")[1]
    assert row["oid"] == 170587117485817955
    assert row["measurement_id"] == 170587117719126124
    fields = dict(build("query_detections", [row]).records[0].fields)
    assert fields["identity.object_id"] == row["oid"]
    assert fields["identity.source_id"] == row["measurement_id"]
    assert fields["identity.object_id"] != fields["identity.source_id"]
    assert type(fields["identity.object_id"]) is type(fields["identity.source_id"]) is int

def test_detection_aliases_and_absent_relationship_ids_hold_across_full_capture():
    for rows in (
        fixture("query_detections"),
        fixture("query_lightcurve")["detections"],
    ):
        assert all(row["diaObjectId"] == row["oid"] for row in rows)
        assert all(row["ssObjectId"] == 0 for row in rows)
        assert all(row["parentDiaSourceId"] == 0 for row in rows)


@pytest.mark.parametrize("endpoint", ("query_detections", "query_lightcurve"))
def test_optional_ss_object_id_suppresses_zero_and_preserves_integer(endpoint):
    row = dict(fixture("query_detections")[0])
    payload = [row] if endpoint == "query_detections" else {
        "detections": [row], "non_detections": [], "forced_photometry": [],
    }
    fields = dict(build(endpoint, payload).records[0].fields)
    assert "solar_system.identity.object_id" not in fields
    row["ssObjectId"] = 123456789
    fields = dict(build(endpoint, payload).records[0].fields)
    assert fields["solar_system.identity.object_id"] == 123456789
    assert type(fields["solar_system.identity.object_id"]) is int

def test_is_negative_is_inverted_for_both_boolean_values_without_mutating_fixture():
    original = fixture("query_detections")[0]
    for raw_value, semantic_value in ((False, True), (True, False)):
        row = dict(original)
        row["isNegative"] = raw_value
        fields = dict(build("query_detections", [row]).records[0].fields)
        assert fields["image_metrics.is_positive"] is semantic_value

def test_raw_psf_flags_are_numeric_but_semantic_flags_are_strict_booleans():
    flag_fields = (
        "psfFlux_flag",
        "psfFlux_flag_edge",
        "psfFlux_flag_noGoodPixels",
    )
    semantic_fields = (
        "photometry.g.psf.flags.failed",
        "photometry.g.psf.flags.edge",
        "photometry.g.psf.flags.no_good_pixels",
    )
    for endpoint, rows in (
        ("query_detections", fixture("query_detections")),
        ("query_lightcurve", fixture("query_lightcurve")["detections"]),
    ):
        assert all(type(rows[0][field]) is int for field in flag_fields)
        payload = [rows[0]] if endpoint == "query_detections" else {
            "detections": [rows[0]],
            "non_detections": [],
            "forced_photometry": [],
        }
        fields = dict(build(endpoint, payload).records[0].fields)
        assert all(type(fields[field]) is bool for field in semantic_fields)
        assert all(fields[field] is False for field in semantic_fields)


@pytest.mark.parametrize("endpoint", ("query_detections", "query_lightcurve"))
def test_unsupported_psf_flag_value_is_omitted_instead_of_coerced_to_false(endpoint):
    row = dict(fixture("query_detections")[0])
    row["psfFlux_flag"] = 2
    payload = [row] if endpoint == "query_detections" else {
        "detections": [row], "non_detections": [], "forced_photometry": [],
    }
    fields = dict(build(endpoint, payload).records[0].fields)
    assert "photometry.g.psf.flags.failed" not in fields
    assert fields["photometry.g.psf.flags.edge"] is False


def test_real_forced_row_maps_canonical_forced_photometry_branch():
    row=fixture("query_forced_photometry")[0]; p=build("query_forced_photometry",[row]); f=dict(p.records[0].fields)
    assert p.records[0].semantic_type=="detection@lsst:alerce"
    assert f["forced_photometry.i.psf.flux"]==3118.2173 and f["forced_photometry.i.psf.flux.error"]==256.24115
    assert f["time.mjd"]==61217.425639118446 and f["identity.visit_id"]==2026062500656 and p.edges==()

def test_forced_row_proves_object_and_measurement_id_are_distinct_integers():
    row = fixture("query_forced_photometry")[0]
    fields = dict(build("query_forced_photometry", [row]).records[0].fields)
    assert fields["identity.object_id"] == row["oid"] == 170587117485817955
    assert fields["identity.source_id"] == row["measurement_id"] == 170587118144323588
    assert fields["identity.object_id"] != fields["identity.source_id"]
    assert type(fields["identity.object_id"]) is type(fields["identity.source_id"]) is int

def test_shared_rubin_detection_fields_converge_with_antares_semantic_paths():
    antares_path = Path(__file__).parents[1] / "alertissimo/data_layer/providers/antares/lsst/mappings.yaml"
    registries = {
        "alerce": yaml.safe_load(MAPPINGS.read_text())["mappings"],
        "antares": yaml.safe_load(antares_path.read_text())["mappings"],
    }

    def relative_target(provider, raw):
        matches = [
            target.split(f"@lsst:{provider}.", 1)[1]
            for target, sources in registries[provider].items()
            if raw in sources and target.startswith(f"detection@lsst:{provider}.")
        ]
        assert len(matches) == 1
        return matches[0]

    shared_fields = {
        "oid": "diaObjectId",
        "measurement_id": "diaSourceId",
        "visit": "visit",
        "detector": "detector",
        "mjd": "midpointMjdTai",
        "ra": "ra",
        "dec": "dec",
        "x": "x",
        "y": "y",
        "reliability": "reliability",
        "snr": "snr",
        "psfFlux": "psfFlux",
        "psfFluxErr": "psfFluxErr",
        "apFlux": "apFlux",
        "apFluxErr": "apFluxErr",
        "isNegative": "isNegative",
        "timeProcessedMjdTai": "timeProcessedMjdTai",
        "scienceFlux": "scienceFlux",
        "scienceFluxErr": "scienceFluxErr",
        "forced_PsfFlux_flag": "forced_PsfFlux_flag",
        "forced_PsfFlux_flag_edge": "forced_PsfFlux_flag_edge",
        "forced_PsfFlux_flag_noGoodPixels": "forced_PsfFlux_flag_noGoodPixels",
        "templateFlux": "templateFlux",
        "templateFluxErr": "templateFluxErr",
    }
    for alerce_raw, antares_raw in shared_fields.items():
        assert relative_target("alerce", f"query_detections#{alerce_raw}") == relative_target(
            "antares", f"locus_alerts#properties.lsst_diaSource_{antares_raw}"
        )

def test_probability_row_is_classifier_produced_assessment_not_computed_best():
    row=fixture("query_probabilities")[0]; r=build("query_probabilities",[row]).records[0]
    assert r.semantic_type=="classification@stamp_classifier_rubin_beta:alerce"
    assert dict(r.fields)=={"provenance.producer.name":"stamp_classifier_rubin_beta","provenance.producer.version":201,"assessment.sn.class":"SN","assessment.sn.probability":0.1623767}
    assert "best.class" not in r.fields

def test_lightcurve_delegates_all_three_branches_without_edges():
    p=build("query_lightcurve",fixture("query_lightcurve"))
    detections=[r for r in p.records if r.semantic_type=="detection@lsst:alerce"]
    lightcurves=[r for r in p.records if r.semantic_type=="lightcurve@lsst:alerce"]
    assert len(detections)==26
    assert len(lightcurves)==1
    assert {r.internal_source.payload_key for r in detections}=={"query_lightcurve.detections","query_lightcurve.forced_photometry"}
    assert lightcurves[0].internal_source is None
    assert len(lightcurves[0].fields["points"])==16
    assert len(lightcurves[0].fields["forced_photometry_points"])==10
    assert p.edges==()

def test_unsupported_methods_have_no_active_payload_definitions():
    text=MAPPINGS.read_text(); assert "query_magstats:" not in text and "query_features:" not in text