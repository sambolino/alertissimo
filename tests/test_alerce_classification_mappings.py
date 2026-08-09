from pathlib import Path

import pytest
import yaml


REGISTRY = Path("alertissimo/core/brokers/registry/alerce")


@pytest.mark.parametrize("survey", ["lsst", "ztf"])
def test_classifier_probability_rows_are_assessment_outputs(survey):
    document = yaml.safe_load((REGISTRY / survey / "mappings.yaml").read_text(encoding="utf-8"))
    prefix = f"classification@{survey}:alerce.assessment.{{output}}"
    assert document["mappings"][prefix] == [
        "query_probabilities#classifier_name", "query_probabilities#classifier_version",
    ]
    assert document["mappings"][f"{prefix}.class"] == ["query_probabilities#class_name"]
    assert document["mappings"][f"{prefix}.probability"] == ["query_probabilities#probability"]


@pytest.mark.parametrize("survey", ["lsst", "ztf"])
def test_mappings_do_not_restore_legacy_helpers_or_raw_paths(survey):
    document = yaml.safe_load((REGISTRY / survey / "mappings.yaml").read_text(encoding="utf-8"))
    assert not ({"sources", "field_status", "availability", "source_fields"} & document.keys())
    for semantic, references in document["mappings"].items():
        assert "step_id_corr" not in semantic
        assert ".raw." not in semantic
        assert all("#detections." not in ref for ref in references)
        assert all("#forced_photometry." not in ref for ref in references)
        assert all("#non_detections." not in ref for ref in references)
