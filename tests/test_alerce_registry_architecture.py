from pathlib import Path

import pytest
import yaml


REGISTRY = Path("alertissimo/core/brokers/registry/alerce")
ORIGINS = ("lsst", "ztf")
FORBIDDEN_ENDPOINT_KEYS = {
    "input", "value_from", "binding", "required_inputs", "optional_inputs", "capabilities"
}


def load(origin, filename):
    with (REGISTRY / origin / filename).open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


@pytest.mark.parametrize("origin", ORIGINS)
def test_endpoints_remain_physical_contracts(origin):
    endpoints = load(origin, "endpoints.yaml")["endpoints"]
    for name, endpoint in endpoints.items():
        if endpoint.get("enabled"):
            assert endpoint.get("operation_types"), name
        assert not (set(endpoint) & FORBIDDEN_ENDPOINT_KEYS), name
        assert all("@" not in operation and ":" not in operation for operation in endpoint.get("operation_types", []))
        params = endpoint.get("params", {})
        for parameter, definition in params.items():
            assert definition.get("description"), f"{name}.{parameter}"
            assert not (set(definition) & FORBIDDEN_ENDPOINT_KEYS), f"{name}.{parameter}"
        assert set(endpoint.get("server_filters", [])) <= set(params), name


@pytest.mark.parametrize("origin", ORIGINS)
def test_nested_lightcurve_payload_paths_are_row_collections(origin):
    payloads = load(origin, "mappings.yaml")["payloads"]
    for collection in ("detections", "non_detections", "forced_photometry"):
        payload = payloads[f"query_lightcurve.{collection}"]
        assert payload["endpoint"] == "query_lightcurve"
        assert payload["path"] == f"{collection}[]"


@pytest.mark.parametrize("origin", ORIGINS)
def test_mapping_references_and_semantic_paths_preserve_architecture(origin):
    mappings = load(origin, "mappings.yaml")["mappings"]
    assert all("step_id_corr" not in reference for references in mappings.values() for reference in references)
    assert all(".raw." not in path for path in mappings)
    assert all(".classifier." not in path for path in mappings)
    for references in mappings.values():
        for reference in references:
            assert not any(f"#{collection}." in reference for collection in (
                "detections", "non_detections", "forced_photometry"
            ))
            if reference.startswith("query_lightcurve#"):
                assert reference in {"query_lightcurve#object_id", "query_lightcurve#oid"}
