"""Authoritative ALeRCE 2.3.1 multisurvey LSST payload audit."""
from __future__ import annotations
from itertools import count
import json
from pathlib import Path
import pytest
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

def test_query_objects_same_oid_preserves_classifier_records_and_row_association():
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
        dict(record.fields) == {"identity.object_id": 170587117485817955}
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
        "detections": [row],
        "non_detections": [],
        "forced_photometry": [],
    }
    fields = dict(build(endpoint, payload).records[0].fields)
    assert "photometry.g.psf.flags.failed" not in fields
    assert fields["photometry.g.psf.flags.edge"] is False


def test_real_forced_row_maps_canonical_forced_photometry_branch():
    row=fixture("query_forced_photometry")[0]; p=build("query_forced_photometry",[row]); f=dict(p.records[0].fields)
    assert p.records[0].semantic_type=="detection@lsst:alerce"
    assert f["forced_photometry.i.psf.flux"]==3118.2173 and f["forced_photometry.i.psf.flux.error"]==256.24115
    assert f["time.mjd"]==61217.425639118446 and f["identity.visit_id"]==2026062500656 and p.edges==()

def test_probability_row_is_classifier_produced_assessment_not_computed_best():
    row=fixture("query_probabilities")[0]; r=build("query_probabilities",[row]).records[0]
    assert r.semantic_type=="classification@stamp_classifier_rubin_beta:alerce"
    assert dict(r.fields)=={"provenance.producer.name":"stamp_classifier_rubin_beta","provenance.producer.version":201,"assessment.sn.class":"SN","assessment.sn.probability":0.1623767}
    assert "best.class" not in r.fields

def test_lightcurve_delegates_all_three_branches_without_edges():
    p=build("query_lightcurve",fixture("query_lightcurve"))
    assert len(p.records)==26 and {r.internal_source.payload_key for r in p.records}=={"query_lightcurve.detections","query_lightcurve.forced_photometry"}
    assert p.edges==()

def test_unsupported_methods_have_no_active_payload_definitions():
    text=MAPPINGS.read_text(); assert "query_magstats:" not in text and "query_features:" not in text
