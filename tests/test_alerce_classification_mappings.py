from pathlib import Path

import pytest
import yaml

from alertissimo.core.brokers.registry.mapping_schema import validate_mapping_file


ROOT = Path("alertissimo/core/brokers/registry/alerce")


def refs(document):
    return {reference for values in document["mappings"].values() for reference in values}


def unmapped_refs(document):
    return {next(iter(entry)) for entry in document["unmapped"]}


@pytest.mark.parametrize("origin", ["lsst", "ztf"])
def test_probability_rows_are_named_assessments(origin):
    directory = ROOT / origin
    mappings = yaml.safe_load((directory / "mappings.yaml").read_text())
    unmapped = yaml.safe_load((directory / "unmapped_fields.yaml").read_text())
    base = f"classification@{origin}:alerce.assessment.{{output}}"
    assert "query_probabilities#classifier_name" in mappings["mappings"][base]
    assert "query_probabilities#classifier_version" in mappings["mappings"][base]
    assert "query_probabilities#class_name" in mappings["mappings"][base + ".class"]
    assert "query_probabilities#probability" in mappings["mappings"][base + ".probability"]
    assert "query_probabilities#ranking" in mappings["mappings"][base + ".ranking"]
    assert "query_probabilities#classifier_name" not in unmapped_refs(unmapped)
    assert "query_probabilities#classifier_version" not in unmapped_refs(unmapped)


@pytest.mark.parametrize("origin", ["lsst", "ztf"])
def test_mappings_have_no_deferred_or_malformed_semantics(origin):
    directory = ROOT / origin
    document = yaml.safe_load((directory / "mappings.yaml").read_text())
    unmapped = yaml.safe_load((directory / "unmapped_fields.yaml").read_text())
    mapped = refs(document)
    deferred = unmapped_refs(unmapped)
    assert mapped.isdisjoint(deferred)
    assert not any(".classifier." in semantic or ".raw." in semantic or "step_id_corr" in semantic
                   for semantic in document["mappings"])
    assert not any("step_id_corr" in reference for reference in mapped)
    assert not any(marker in reference for reference in mapped
                   for marker in ("#detections.", "#forced_photometry.", "#non_detections."))
    assert not any(reference.startswith("query_lightcurve#") for reference in mapped | deferred)
    validate_mapping_file(directory / "mappings.yaml")
