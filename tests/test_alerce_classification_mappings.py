from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).parents[1] / "alertissimo/core/brokers/registry/alerce"


@pytest.mark.parametrize("origin", ("lsst", "ztf"))
def test_probability_fields_use_assessment_namespace_carrier(origin):
    document = yaml.safe_load((ROOT / origin / "mappings.yaml").read_text())
    mappings = document["mappings"]
    base = f"classification@{origin}:alerce.assessment.{{output}}"
    expected = {
        "query_probabilities#classifier_name": base,
        "query_probabilities#classifier_version": base,
        "query_probabilities#class_name": f"{base}.class",
        "query_probabilities#probability": f"{base}.probability",
    }
    locations = {}
    for semantic_path, references in mappings.items():
        for reference in references:
            if reference in expected:
                locations.setdefault(reference, []).append(semantic_path)
    assert locations == {reference: [path] for reference, path in expected.items()}
    assert not any(".classifier." in path for path in mappings)
    assert not any(
        ref == "query_probabilities#ranking"
        for references in mappings.values()
        for ref in references
    )
