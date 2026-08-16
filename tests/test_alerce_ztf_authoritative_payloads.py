"""Audits and semantic assertions over authoritative ALeRCE 2.3.1 bytes."""

from __future__ import annotations

from itertools import count
import json
from pathlib import Path

import pytest

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

FIXTURES = Path(__file__).parent / "fixtures" / "alerce" / "ztf"
MAPPINGS = (
    Path(__file__).parents[1]
    / "alertissimo/data_layer/providers/alerce/ztf/mappings.yaml"
)
ENDPOINTS = (
    "query_objects",
    "query_object",
    "query_detections",
    "query_non_detections",
    "query_forced_photometry",
    "query_lightcurve",
    "query_probabilities",
    "query_magstats",
    "query_features",
)


def _fixture(endpoint: str):
    return json.loads((FIXTURES / f"{endpoint}.json").read_text(encoding="utf-8"))


def _build(endpoint: str, payload):
    execution_id = InternalExecutionId(f"execution:fixture:{endpoint}")
    ids = count()
    return build_portfolio_from_execution(
        ExecutionResult(
            payload=payload,
            execution_provenance=InternalExecutionProvenance(
                internal_execution_id=execution_id,
                broker="alerce",
                origin="ztf",
                endpoint=endpoint,
            ),
        ),
        mappings_path=MAPPINGS,
        internal_portfolio_id=InternalPortfolioId("portfolio:fixture"),
        record_id_factory=lambda: InternalRecordId(f"record:{next(ids)}"),
        validate_semantic_model=True,
    )


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_every_authoritative_fixture_has_zero_unaccounted_leaves(endpoint):
    path = FIXTURES / f"{endpoint}.json"
    report = audit_payload(
        _fixture(endpoint),
        broker="alerce",
        origin="ztf",
        endpoint=endpoint,
        payload_file=str(path),
    )
    assert "Unaccounted leaves:\n  (none)" in report
    assert "Unaccounted leaves: 0" in report


def test_query_objects_wrapper_is_structural_and_items_are_selected():
    payload = _fixture("query_objects")
    assert set(payload) == {
        "total", "page", "next", "has_next", "prev", "has_prev", "items"
    }
    assert len(payload["items"]) == 4
    report = audit_payload(
        payload, broker="alerce", origin="ztf", endpoint="query_objects"
    )
    assert "Delegated / structural leaves: 6" in report
    execution_id = InternalExecutionId("execution:fixture:query_objects")
    portfolios = build_portfolios_from_execution(
        ExecutionResult(
            payload=payload,
            execution_provenance=InternalExecutionProvenance(
                internal_execution_id=execution_id,
                broker="alerce",
                origin="ztf",
                endpoint="query_objects",
            ),
        ),
        mappings_path=MAPPINGS,
        validate_semantic_model=True,
    )
    assert len(portfolios) == 4
    assert len({portfolio.internal_portfolio_id for portfolio in portfolios}) == 4
    summaries = [
        record
        for portfolio in portfolios
        for record in portfolio.records
        if record.semantic_type == "summary@ztf:alerce"
    ]
    assert len(summaries) == 4
    expected_oids = {item["oid"] for item in payload["items"]}
    assert {record.fields["identity.object_id"] for record in summaries} == expected_oids
    for portfolio in portfolios:
        object_summaries = [
            record for record in portfolio.records
            if record.semantic_type == "summary@ztf:alerce"
        ]
        assert len(object_summaries) == 1
        assert portfolio.executions[0].internal_execution_id == execution_id
        assert object_summaries[0].fields["identity.object_id"] in expected_oids
        assert portfolio.edges == ()
    fields = dict(summaries[0].fields)
    assert fields["identity.object_id"] == "ZTF18abbuksn"
    assert fields["position.ra"] == 313.7733232785203
    assert fields["position.dec"] == 39.09800386874637
    assert fields["time.first_mjd"] == 58286.42961810017
    assert fields["time.last_mjd"] == 61032.09531249991


def test_query_object_has_real_summary_and_no_fabricated_classification():
    portfolio = _build("query_object", _fixture("query_object"))
    assert [r.semantic_type for r in portfolio.records] == ["summary@ztf:alerce"]
    fields = dict(portfolio.records[0].fields)
    assert fields["identity.object_id"] == "ZTF18abbuksn"
    assert fields["position.ra_error"] == 0.002804951162654439
    assert fields["time.timespan_days"] == 2745.665694399737
    assert not any(r.semantic_type.startswith("classification@") for r in portfolio.records)
    assert portfolio.edges == ()


def test_real_detection_and_non_detection_photometry():
    detection = _fixture("query_detections")[0]
    portfolio = _build("query_detections", [detection])
    fields = dict(portfolio.records[0].fields)
    assert fields["photometry.g.psf.mag"] == 17.579912
    assert fields["photometry.g.psf.mag.error"] == 0.025473464
    assert fields["photometry.g.psf.mag.corrected"] == 15.443523
    assert fields["photometry.g.psf.mag.corrected.error"] == 100.0
    assert fields["photometry.g.psf.mag.corrected.extended_component_error"] == 0.0035606765
    assert fields["photometry.g.aperture.mag"] == 17.6296
    assert fields["image_metrics.is_positive"] is True

    nondetection = _fixture("query_non_detections")[0]
    fields = dict(_build("query_non_detections", [nondetection]).records[0].fields)
    assert fields["time.mjd"] == 58288.435289400164
    assert fields["photometry.g.limit.mag"] == 20.1306
    # Endpoint context cannot currently inject this provider-neutral constant.
    assert "photometry.g.limit.upper_limit" not in fields


def test_real_forced_photometry_astrometry_calibration_and_reference_source():
    row = _fixture("query_forced_photometry")[0]
    portfolio = _build("query_forced_photometry", [row])
    fields = dict(portfolio.records[0].fields)
    assert fields["identity.object_id"] == "ZTF18abbuksn"
    assert fields["position.ra"] == 313.7732871
    assert fields["position.dec"] == 39.0979821
    assert fields["time.mjd"] == 60911.23585649999
    assert fields["time.exposure"] == 30.0
    assert fields["forced_photometry.g.mag"] == 17.28768539428711
    assert fields["forced_photometry.g.mag.error"] == 0.010026260279119015
    assert fields["forced_photometry.g.mag.corrected"] == 15.397634320165597
    assert fields["forced_photometry.g.mag.corrected.error"] == 100.0
    assert fields["forced_photometry.g.mag.corrected.extended_component_error"] == 0.0017584035219804597
    assert fields["calibration.g.zero_point"] == 26.351499557495117
    assert fields["calibration.g.zero_point_uncertainty"] == 5.07220011058962e-06
    assert fields["calibration.g.zero_point_rms"] == 0.023729000240564346
    assert fields["reference_image.nearest_source.position.ra"] == 313.7733154296875
    assert fields["reference_image.nearest_source.position.dec"] == 39.098026275634766
    assert fields["reference_image.nearest_source.photometry.g.mag"] == 15.606999397277832
    assert fields["reference_image.nearest_source.photometry.g.mag.error"] == 0.01899999938905239
    assert fields["image_metrics.is_positive"] is True
    assert portfolio.edges == ()


@pytest.mark.parametrize(
    ("value", "expected"), [(1, True), ("1", True), (-1, False), ("-1", False)]
)
def test_strict_isdiffpos_transform_on_detection_branches(value, expected):
    row = dict(_fixture("query_detections")[0], isdiffpos=value)
    fields = _build("query_detections", [row]).records[0].fields
    assert fields["image_metrics.is_positive"] is expected


def test_unknown_isdiffpos_is_omitted():
    row = dict(_fixture("query_detections")[0], isdiffpos=0)
    assert "image_metrics.is_positive" not in _build("query_detections", [row]).records[0].fields


def test_real_classifier_row_uses_classifier_as_producer_and_alerce_as_channel():
    row = _fixture("query_probabilities")[0]
    portfolio = _build("query_probabilities", [row])
    record = portfolio.records[0]
    assert record.semantic_type == "classification@lc_classifier:alerce"
    assert dict(record.fields) == {
        "provenance.producer.name": "lc_classifier",
        "provenance.producer.version": "hierarchical_rf_1.1.0",
        "assessment.snia.class": "SNIa",
        "assessment.snia.probability": 0.0082,
    }
    assert portfolio.edges == ()
