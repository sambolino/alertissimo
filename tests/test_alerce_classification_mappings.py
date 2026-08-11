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
from alertissimo.data_layer.runtime.record_builder import build_portfolio_from_execution


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
