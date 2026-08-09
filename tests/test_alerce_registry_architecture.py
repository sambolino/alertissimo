from pathlib import Path
import yaml

ROOT = Path(__file__).parents[1]
ALERCE = ROOT / "alertissimo/core/brokers/registry/alerce"
SURVEYS = ("lsst", "ztf")
FORBIDDEN_ENDPOINT_KEYS = {"input", "value_from", "binding", "required_inputs", "optional_inputs", "capabilities"}


def load(survey, name):
    return yaml.safe_load((ALERCE / survey / name).read_text())


def walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_keys(child)


def test_semantic_and_raw_mapping_blockers_are_absent():
    for survey in SURVEYS:
        mappings = load(survey, "mappings.yaml")["mappings"]
        assert all("step_id_corr" not in path for path in mappings)
        assert all(".classifier." not in path and ".raw." not in path for path in mappings)
        forbidden = {f"classification@{survey}:alerce.{leaf}" for leaf in ("class", "probability", "ranking")}
        assert forbidden.isdisjoint(mappings)
        references = [reference for values in mappings.values() for reference in values]
        assert all("step_id_corr" not in reference for reference in references)


def test_lightcurve_row_references_are_scoped_to_nested_payloads():
    ztf = load("ztf", "mappings.yaml")["mappings"]
    references = [reference for values in ztf.values() for reference in values]
    assert any(reference.startswith("query_lightcurve.detections#") for reference in references)
    assert any(reference.startswith("query_lightcurve.forced_photometry#") for reference in references)
    assert any(reference.startswith("query_lightcurve.non_detections#") for reference in references)
    assert not any(reference.startswith("query_lightcurve#") for reference in references)
    assert not any("#detections." in reference or "#forced_photometry." in reference or "#non_detections." in reference for reference in references)


def test_payload_paths_distinguish_root_objects_and_lists():
    for survey in SURVEYS:
        payloads = load(survey, "mappings.yaml")["payloads"]
        assert payloads["query_object"]["path"] == "."
        assert payloads["get_avro"]["path"] == "."
        assert payloads["query_object"]["path"] != "[]"
        assert payloads["query_lightcurve.detections"]["path"] == "detections[]"
        assert payloads["query_lightcurve.forced_photometry"]["path"] == "forced_photometry[]"
        assert payloads["query_lightcurve.non_detections"]["path"] == "non_detections[]"


def test_endpoint_contracts_use_only_physical_described_params():
    for survey in SURVEYS:
        endpoints = load(survey, "endpoints.yaml")
        assert FORBIDDEN_ENDPOINT_KEYS.isdisjoint(walk_keys(endpoints))
        for endpoint in endpoints["endpoints"].values():
            for name, definition in (endpoint.get("params") or {}).items():
                assert isinstance(name, str) and name
                assert definition.get("description")


def test_planner_terms_was_not_added():
    assert not list(ALERCE.rglob("planner_terms.yaml"))
