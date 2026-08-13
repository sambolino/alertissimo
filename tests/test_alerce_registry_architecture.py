from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).parents[1] / "alertissimo/data_layer/providers/alerce"
ORIGINS = ("lsst", "ztf")
ROW_PAYLOADS = {
    "query_lightcurve.detections": "detections[]",
    "query_lightcurve.non_detections": "non_detections[]",
}


def load(origin, filename):
    return yaml.safe_load((ROOT / origin / filename).read_text())


@pytest.mark.parametrize("origin", ORIGINS)
def test_payload_shapes_and_semantic_paths(origin):
    document = load(origin, "mappings.yaml")
    payloads = document["payloads"]
    assert payloads["query_objects"]["path"] == (
        "items[]" if origin == "ztf" else "[]"
    )
    assert payloads["query_object"]["path"] == "."
    assert payloads["query_lightcurve"]["path"] == "."
    for payload, path in ROW_PAYLOADS.items():
        assert payloads[payload]["path"] == path
        assert payloads[payload]["endpoint"] == "query_lightcurve"
    if origin == "lsst":
        assert payloads["query_lightcurve.forced_photometry"]["path"] == "forced_photometry[]"
    else:
        assert "query_lightcurve.forced_photometry" not in payloads

    for semantic_path, references in document["mappings"].items():
        assert ".raw." not in semantic_path
        assert ".classifier." not in semantic_path
        if semantic_path.startswith(("detection@", "non_detection@", "forced_photometry@")):
            assert not any(ref.startswith("query_lightcurve#") for ref in references)


@pytest.mark.parametrize("origin", ORIGINS)
def test_unmapped_is_disjoint_and_excludes_lightcurve_containers(origin):
    mappings = load(origin, "mappings.yaml")["mappings"]
    unmapped = load(origin, "unmapped_fields.yaml")["unmapped"]
    mapped_refs = {ref for refs in mappings.values() for ref in refs}
    unmapped_refs = {next(iter(entry)) for entry in unmapped}
    assert mapped_refs.isdisjoint(unmapped_refs)
    assert not {
        "query_lightcurve#detections",
        "query_lightcurve#non_detections",
        "query_lightcurve#forced_photometry",
    } & unmapped_refs
    assert "query_probabilities#ranking" in unmapped_refs
    if origin == "ztf":
        assert any("step_id_corr" in ref for ref in unmapped_refs)
    else:
        assert not any("step_id_corr" in ref for ref in unmapped_refs)
    assert not any("step_id_corr" in ref for ref in mapped_refs)


@pytest.mark.parametrize("origin", ORIGINS)
def test_endpoints_remain_physical_contracts(origin):
    endpoints = load(origin, "endpoints.yaml")["endpoints"]
    forbidden = {
        "input", "value_from", "binding", "required_inputs", "optional_inputs",
        "capabilities",
    }
    for endpoint in endpoints.values():
        assert endpoint.get("operation_types")
        assert set(endpoint.get("server_filters", ())) <= set(endpoint.get("params", {}))
        assert "post_filter" in endpoint
        for name, parameter in endpoint.get("params", {}).items():
            assert parameter.get("description"), name
        stack = [endpoint]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                assert forbidden.isdisjoint(value)
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)


def test_lsst_query_probabilities_excludes_unsupported_classifier_argument():
    endpoint = load("lsst", "endpoints.yaml")["endpoints"]["query_probabilities"]
    assert "classifier" not in endpoint["params"]
    assert "classifier" not in endpoint["server_filters"]
