from itertools import count
from pathlib import Path

import yaml

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
    InternalPortfolioId,
    InternalRecordId,
)
from alertissimo.data_layer.runtime.record_builder import (
    _resolve_dynamic_field_paths,
    build_portfolio_from_execution,
)


MAPPINGS = Path(__file__).parents[1] / "alertissimo/data_layer/providers/alerce/ztf/mappings.yaml"


def _build(endpoint, payload):
    execution_id = InternalExecutionId(f"execution:{endpoint}")
    execution = ExecutionResult(
        payload=payload,
        execution_provenance=InternalExecutionProvenance(
            internal_execution_id=execution_id,
            broker="alerce",
            origin="ztf",
            endpoint=endpoint,
        ),
    )
    ids = count()
    return build_portfolio_from_execution(
        execution,
        mappings_path=MAPPINGS,
        internal_portfolio_id=InternalPortfolioId("portfolio:test"),
        record_id_factory=lambda: InternalRecordId(f"record:{next(ids)}"),
        validate_semantic_model=True,
    )


def test_query_object_selected_result_is_classifier_produced_record():
    portfolio = _build(
        "query_object",
        {"oid": "ZTF21aaeyldq", "classifier": "lc_classifier", "class": "SN Ia", "probability": 0.91},
    )
    classification = [record for record in portfolio.records if record.semantic_type.startswith("classification@")]
    assert len(classification) == 1
    assert classification[0].semantic_type == "classification@lc_classifier:alerce"
    assert dict(classification[0].fields) == {
        "best.class": "SN Ia",
        "best.probability": 0.91,
        "provenance.producer.name": "lc_classifier",
    }


def test_probability_version_is_provenance_and_class_is_assessment_namespace():
    portfolio = _build(
        "query_probabilities",
        [{"classifier_name": "Stamp Classifier", "classifier_version": "1.2.0", "class_name": "SN Ia", "probability": 0.82}],
    )
    record = portfolio.records[0]
    assert record.semantic_type == "classification@stamp_classifier:alerce"
    assert record.fields["provenance.producer.name"] == "Stamp Classifier"
    assert record.fields["provenance.producer.version"] == "1.2.0"
    assert record.fields["assessment.sn_ia.class"] == "SN Ia"
    assert record.fields["assessment.sn_ia.probability"] == 0.82
    assert not any("1.2.0" in field for field in record.fields)


def test_filter_specific_calibration_paths_are_bound_from_fid():
    portfolio = _build(
        "query_forced_photometry",
        [{"fid": 1, "magzpsci": 26.3, "clrcoeff": -0.04, "clrcounc": 0.01}],
    )
    fields = portfolio.records[0].fields
    assert fields["calibration.g.zero_point"] == 26.3
    assert fields["calibration.g.color_coefficient"] == -0.04
    assert fields["calibration.g.color_coefficient_uncertainty"] == 0.01
    assert "calibration.color_coefficient" not in fields


def test_only_declared_identifier_placeholders_are_slugified():
    assert _resolve_dynamic_field_paths({
        "assessment.{output}": "SN Ia",
        "assessment.{output}.probability": 0.82,
    }) == {"assessment.sn_ia.probability": 0.82}
    assert _resolve_dynamic_field_paths({
        "photometry.{filter}": "g",
        "photometry.{filter}.mag": 19.1,
    }) == {"photometry.g.mag": 19.1}
    assert _resolve_dynamic_field_paths({
        "result.{method}": "Human Label",
        "result.{method}.value": 1,
    }) == {"result.Human Label.value": 1}


def test_isdiffpos_uses_ztf_sign_semantics_without_unsafe_default():
    portfolio = _build("query_forced_photometry", [
        {"fid": 1, "isdiffpos": 1, "mjd": 1.0},
        {"fid": 1, "isdiffpos": -1, "mjd": 2.0},
        {"fid": 1, "isdiffpos": "unexpected", "mjd": 3.0},
    ])
    records = sorted(
        (
            record
            for record in portfolio.records
            if record.semantic_type == "detection@ztf:alerce"
        ),
        key=lambda record: record.fields["time.mjd"],
    )
    assert records[0].fields["image_metrics.is_positive"] is True
    assert records[1].fields["image_metrics.is_positive"] is False
    assert "image_metrics.is_positive" not in records[2].fields


def test_payload_selection_uses_only_authoritative_nested_lightcurve_rows():
    object_portfolio = _build("query_object", {
        "oid": "ZTF-object", "candid": 999, "classifier_name": "wrong endpoint",
    })
    assert [record.semantic_type for record in object_portfolio.records] == ["summary@ztf:alerce"]

    lightcurve = _build("query_lightcurve", {
        "detections": [{"oid": "ZTF-detection", "fid": 1, "mjd": 1.0}],
        "non_detections": [{"oid": "ZTF-limit", "fid": 2, "mjd": 2.0, "diffmaglim": 20.2}],
    })
    detections = [
        record
        for record in lightcurve.records
        if record.semantic_type == "detection@ztf:alerce"
    ]
    lightcurves = [
        record
        for record in lightcurve.records
        if record.semantic_type == "lightcurve@ztf:alerce"
    ]
    expected_payloads = {
        "query_lightcurve.detections",
        "query_lightcurve.non_detections",
    }
    assert len(detections) == 2
    assert len(lightcurves) == 1
    assert {record.internal_source.payload_key for record in detections} == expected_payloads
    assert lightcurves[0].internal_source is None
    assert len(lightcurves[0].fields["points"]) == 2