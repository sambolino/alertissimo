from pathlib import Path
import yaml
import pytest

ALERCE = Path(__file__).parents[1] / "alertissimo/core/brokers/registry/alerce"


@pytest.mark.parametrize("survey", ["lsst", "ztf"])
def test_probability_fields_only_use_assessment_paths(survey):
    mappings = yaml.safe_load((ALERCE / survey / "mappings.yaml").read_text())["mappings"]
    expected = {
        "query_probabilities#classifier_name": f"classification@{survey}:alerce.assessment.{{output}}",
        "query_probabilities#classifier_version": f"classification@{survey}:alerce.assessment.{{output}}",
        "query_probabilities#class_name": f"classification@{survey}:alerce.assessment.{{output}}.class",
        "query_probabilities#probability": f"classification@{survey}:alerce.assessment.{{output}}.probability",
    }
    locations = {}
    for semantic_path, references in mappings.items():
        for reference in references:
            locations.setdefault(reference, []).append(semantic_path)
    for reference, semantic_path in expected.items():
        assert locations.get(reference) == [semantic_path]
    assert "query_probabilities#ranking" not in locations
