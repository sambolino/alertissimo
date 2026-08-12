"""Fixture-driven audit of authoritative ANTARES/ZTF 1.14.0 payloads."""
from __future__ import annotations

from copy import deepcopy
from itertools import count
import json
from pathlib import Path

import yaml

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId, InternalExecutionProvenance, InternalPortfolioId,
    InternalRecordId,
)
from alertissimo.data_layer.runtime.record_builder import build_portfolio_from_execution
from tools.audit_payload_mapping_coverage import audit_payload

FIXTURES = Path(__file__).parent / "fixtures" / "antares" / "ztf"
MAPPINGS = Path(__file__).parents[1] / "alertissimo/data_layer/providers/antares/ztf/mappings.yaml"
DEBT = MAPPINGS.with_name("unmapped_fields.yaml")


def _fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _build(endpoint, payload):
    ids = count()
    return build_portfolio_from_execution(
        ExecutionResult(payload=payload, execution_provenance=InternalExecutionProvenance(
            internal_execution_id=InternalExecutionId(f"execution:fixture:{endpoint}"),
            broker="antares", origin="ztf", endpoint=endpoint,
        )), mappings_path=MAPPINGS,
        internal_portfolio_id=InternalPortfolioId("portfolio:fixture"),
        record_id_factory=lambda: InternalRecordId(f"record:{next(ids)}"),
        validate_semantic_model=True,
    )


def _alert_payload(rows=None):
    return {"alerts": _fixture("alerts") if rows is None else rows}


def test_alert_leaf_audit_is_exhaustive_and_fixture_driven():
    report = audit_payload(_alert_payload(), broker="antares", origin="ztf",
                           endpoint="get_by_ztf_object_id")
    assert "Observed leaves: 117" in report
    assert "Mapped leaves: 36" in report
    assert "Intentionally unmapped leaves: 81" in report
    assert "Unaccounted leaves: 0" in report
    assert "Unaccounted leaves:\n  (none)" in report


def test_lightcurve_secondary_surface_has_real_fourteen_column_audit():
    rows = _fixture("lightcurve")
    observed = {key for row in rows for key in row}
    document = yaml.safe_load(DEBT.read_text(encoding="utf-8"))
    debt = {
        next(iter(entry)).split("#", 1)[1]
        for entry in document["unmapped"]
        if next(iter(entry)).startswith("lightcurve_secondary#")
    }
    mappings = yaml.safe_load(MAPPINGS.read_text(encoding="utf-8"))["mappings"]
    mapped = {
        ref.split("#", 1)[1] for refs in mappings.values() for ref in refs
        if ref.startswith("lightcurve_secondary#")
    }
    assert len(rows) == 280
    assert len(observed) == 14
    assert mapped == set()
    assert observed == debt
    assert observed - mapped - debt == set()
    assert _build("lightcurve", rows).records == ()
    assert len(_build("get_by_ztf_object_id", _alert_payload()).records) == 316


def test_alerts_build_exactly_one_detection_each_without_edges():
    portfolio = _build("get_by_ztf_object_id", _alert_payload())
    assert len(portfolio.records) == 316
    assert {r.semantic_type for r in portfolio.records} == {"detection@ztf:antares"}
    assert portfolio.edges == ()
    fields = [dict(r.fields) for r in portfolio.records]
    assert sum(f["photometry.r.limit.upper_limit"] for f in fields if "photometry.r.limit.upper_limit" in f) + sum(f["photometry.g.limit.upper_limit"] for f in fields if "photometry.g.limit.upper_limit" in f) == 246
    assert sum(not next(v for k,v in f.items() if k.endswith("limit.upper_limit")) for f in fields) == 70
    assert all("identity.alert_id" in f for f in fields)
    assert not any("photometry.R" in key for f in fields for key in f)
    assert not any(key.startswith(("non_detection", "forced_photometry")) for f in fields for key in f)


def test_converged_ztf_science_fields_use_authoritative_values():
    row = _fixture("alerts")[32]
    fields = dict(_build("get_by_ztf_object_id", _alert_payload([row])).records[0].fields)
    assert fields["identity.alert_id"] == "ztf_candidate:1113163781415010010"
    assert fields["photometry.g.aperture.mag"] == 17.104700088500977
    assert fields["photometry.g.aperture.large.mag_error"] == 0.3098999857902527
    assert fields["time.exposure"] == 30.0
    assert fields["calibration.g.zero_point"] == 23.550796508789062
    assert fields["calibration.g.color_coefficient"] == -0.05729600042104721
    assert fields["reference_image.nearest_source.image_metrics.fit_chi"] == 0.6159999966621399
    assert fields["reference_image.nearest_source.image_metrics.sharpness"] == -0.03099999949336052
    assert fields["provenance.processing_id"] == 1113163781415
    assert fields["provenance.reference_image_id"] == 700120114


def test_unknown_passband_cannot_create_an_ontology_filter():
    row = deepcopy(_fixture("alerts")[32])
    row["properties"]["ant_passband"] = "X"
    fields = dict(_build("get_by_ztf_object_id", _alert_payload([row])).records[0].fields)
    assert not any(key.startswith("photometry.X") for key in fields)
    assert not any(key.startswith("photometry.") for key in fields)


def test_unknown_survey_and_isdiffpos_are_strictly_omitted():
    row = deepcopy(_fixture("alerts")[32])
    row["properties"]["ant_survey"] = 999
    row["properties"]["ztf_isdiffpos"] = "unknown"
    fields = dict(_build("get_by_ztf_object_id", _alert_payload([row])).records[0].fields)
    assert not any(key.endswith("limit.upper_limit") for key in fields)
    assert "image_metrics.is_positive" not in fields


def test_known_sentinel_is_not_emitted_as_science():
    row = deepcopy(_fixture("alerts")[32])
    row["properties"]["ztf_magap"] = -999
    fields = dict(_build("get_by_ztf_object_id", _alert_payload([row])).records[0].fields)
    assert "photometry.g.aperture.mag" not in fields


def test_six_authoritative_catalog_surfaces_build_direct_crossmatches():
    locus = _fixture("get_by_ztf_object_id")
    locus["catalog_objects"] = _fixture("catalog_objects")
    portfolio = _build("get_by_ztf_object_id", locus)
    crossmatches = {r.semantic_type: dict(r.fields) for r in portfolio.records
                    if r.semantic_type.startswith("crossmatch@")}
    assert set(crossmatches) == {
        "crossmatch@2mass_psc:antares",
        "crossmatch@allwise:antares",
        "crossmatch@bright_guide_star_cat:antares",
        "crossmatch@gaia_dr3_gaia_source:antares",
        "crossmatch@gaia_dr3_variability:antares",
        "crossmatch@gaia_edr3_distances_bailer_jones:antares",
    }
    assert crossmatches["crossmatch@gaia_dr3_gaia_source:antares"][
        "astrometric_solution.parallax"
    ] == 0.4750640015400165
    assert portfolio.edges == ()
