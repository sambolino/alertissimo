from pathlib import Path

import pytest
import yaml


REGISTRY = Path("alertissimo/core/brokers/registry/alerce")


def load_mappings(origin):
    with (REGISTRY / origin / "mappings.yaml").open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)["mappings"]


@pytest.mark.parametrize("origin", ["lsst", "ztf"])
def test_probability_classifier_namespace_carriers_are_mapped_once(origin):
    mappings = load_mappings(origin)
    assessment = f"classification@{origin}:alerce.assessment.{{output}}"
    expected = {
        "query_probabilities#classifier_name": assessment,
        "query_probabilities#classifier_version": assessment,
        "query_probabilities#class_name": f"{assessment}.class",
        "query_probabilities#probability": f"{assessment}.probability",
    }

    assert assessment in mappings
    assert "query_probabilities#classifier_name" in mappings[assessment]
    assert "query_probabilities#classifier_version" in mappings[assessment]
    for reference, semantic_path in expected.items():
        assert [path for path, references in mappings.items() if reference in references] == [semantic_path]

    assert all(
        "query_probabilities#ranking" not in references
        for references in mappings.values()
    )
