from pathlib import Path

import pytest
import yaml


REGISTRY = Path(__file__).parents[1] / "alertissimo/core/brokers/registry/alerce"
QUERY_PROBABILITY_FIELDS = {
    "classifier_name",
    "classifier_version",
    "class_name",
    "probability",
    "ranking",
}


def load_registry(origin):
    directory = REGISTRY / origin
    with (directory / "mappings.yaml").open(encoding="utf-8") as stream:
        mappings = yaml.safe_load(stream)["mappings"]
    unmapped_path = directory / "unmapped_fields.yaml"
    if not unmapped_path.exists():
        return mappings, set()
    with unmapped_path.open(encoding="utf-8") as stream:
        entries = yaml.safe_load(stream)["unmapped"]
    return mappings, {next(iter(entry)) for entry in entries}


def fields_for_endpoint(mapping, endpoint):
    if "sources" in mapping:
        return {
            source["field"] for source in mapping["sources"]
            if source["endpoint"] == endpoint
        }
    if endpoint in mapping.get("endpoints", []):
        return {mapping.get("field")}
    return set()


@pytest.mark.parametrize("origin", ["lsst", "ztf"])
def test_query_probabilities_use_classifier_identity_as_assessment_namespace(origin):
    mappings, unmapped = load_registry(origin)
    prefix = f"classification@{origin}:alerce.assessment.{{output}}"

    assert "query_probabilities#classifier_name" not in unmapped
    assert "query_probabilities#classifier_version" not in unmapped
    assert fields_for_endpoint(mappings[prefix], "query_probabilities") == {
        "classifier_name", "classifier_version"
    }
    assert mappings[prefix]["role"] == "namespace_carrier"
    assert mappings[prefix]["transform"] == {
        "op": "qualify_namespace",
        "name_field": "classifier_name",
        "version_field": "classifier_version",
        "version_optional": True,
    }
    assert fields_for_endpoint(mappings[f"{prefix}.class"], "query_probabilities") == {
        "class_name"
    }
    assert fields_for_endpoint(
        mappings[f"{prefix}.probability"], "query_probabilities"
    ) == {"probability"}
    assert fields_for_endpoint(mappings[f"{prefix}.ranking"], "query_probabilities") == {
        "ranking"
    }


@pytest.mark.parametrize("origin", ["lsst", "ztf"])
def test_query_probabilities_are_not_best_or_classifier_semantics(origin):
    mappings, _ = load_registry(origin)

    assert not any(".classifier." in path for path in mappings)
    for path, mapping in mappings.items():
        if fields_for_endpoint(mapping, "query_probabilities") & QUERY_PROBABILITY_FIELDS:
            assert ".best." not in path
