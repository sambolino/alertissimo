from pathlib import Path

import yaml


REGISTRY = Path(__file__).parents[1] / "alertissimo/core/brokers/registry/alerce"
ORIGINS = ("lsst", "ztf")
KNOWN_STEP_REFS = {
    "lsst": {"query_object#step_id_corr", "query_objects#step_id_corr"},
    "ztf": {
        "query_object#step_id_corr", "query_objects#step_id_corr",
        "query_detections#step_id_corr", "query_lightcurve.detections#step_id_corr",
    },
}


def load(origin, filename):
    return yaml.safe_load((REGISTRY / origin / filename).read_text())


def unmapped_refs(document):
    return {next(iter(entry)) for entry in document["unmapped"]}


def all_mapping_refs(document):
    return {reference for references in document["mappings"].values() for reference in references}


def test_classifier_namespace_carriers_and_probability_rows_are_scoped():
    for origin in ORIGINS:
        document = load(origin, "mappings.yaml")
        mappings = document["mappings"]
        prefix = f"classification@{origin}:alerce.assessment.{{output}}"
        assert "query_probabilities#classifier_name" in mappings[prefix + ".classifier.name"]
        assert "query_probabilities#classifier_version" in mappings[prefix + ".classifier.version"]
        assert mappings[prefix + ".class"] == ["query_probabilities#class_name"]
        assert mappings[prefix + ".probability"] == ["query_probabilities#probability"]
        probability_refs = {ref for refs in mappings.values() for ref in refs if ref.startswith("query_probabilities#")}
        assert probability_refs == {
            "query_probabilities#classifier_name", "query_probabilities#classifier_version",
            "query_probabilities#class_name", "query_probabilities#probability",
        }
        assert document["payloads"]["query_probabilities"]["path"] == "[]"


def test_unstable_correction_steps_and_probability_ranking_stay_unmapped():
    for origin in ORIGINS:
        mappings = load(origin, "mappings.yaml")
        unmapped = load(origin, "unmapped_fields.yaml")
        mapped = all_mapping_refs(mappings)
        raw_unmapped = unmapped_refs(unmapped)
        step_refs = {ref for ref in raw_unmapped if ref.endswith("#step_id_corr")}
        assert KNOWN_STEP_REFS[origin] <= step_refs
        assert step_refs.isdisjoint(mapped)
        assert "query_probabilities#ranking" in raw_unmapped
        assert "query_probabilities#ranking" not in mapped
