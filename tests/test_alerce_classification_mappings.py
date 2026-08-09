from pathlib import Path

import yaml


def test_probability_row_classifier_mappings_are_preserved():
    registry = Path("alertissimo/core/brokers/registry/alerce")
    for origin in ("lsst", "ztf"):
        with (registry / origin / "mappings.yaml").open(encoding="utf-8") as stream:
            mappings = yaml.safe_load(stream)["mappings"]
        base = f"classification@{origin}:alerce.assessment.{{output}}"
        assert mappings[base] == [
            "query_probabilities#classifier_name",
            "query_probabilities#classifier_version",
        ]
        assert mappings[f"{base}.class"] == ["query_probabilities#class_name"]
        assert mappings[f"{base}.probability"] == ["query_probabilities#probability"]
