from pathlib import Path

import pytest
import yaml


ALERCE_ROOT = Path(__file__).parents[1] / "alertissimo/core/brokers/registry/alerce"
ORIGINS = ("lsst", "ztf")
FORBIDDEN_ENDPOINT_KEYS = {
    "input", "value_from", "binding", "required_inputs", "optional_inputs", "capabilities"
}
SEMANTIC_OPERATION_PREFIXES = ("summary.", "detection.", "classification.", "data_product.")


def load(origin, filename):
    return yaml.safe_load((ALERCE_ROOT / origin / filename).read_text(encoding="utf-8"))


def nested_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from nested_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from nested_keys(child)


@pytest.mark.parametrize("origin", ORIGINS)
def test_endpoint_contracts_are_physical_and_callable(origin):
    endpoints = load(origin, "endpoints.yaml")["endpoints"]
    for name, endpoint in endpoints.items():
        forbidden = FORBIDDEN_ENDPOINT_KEYS.intersection(nested_keys(endpoint))
        assert not forbidden, f"{origin}/{name} contains forbidden keys: {sorted(forbidden)}"
        params = endpoint.get("params", {})
        for param_name, param in params.items():
            assert param.get("description"), f"{origin}/{name}.{param_name} lacks a description"
        if endpoint.get("enabled"):
            operations = endpoint.get("operation_types")
            assert operations, f"enabled endpoint {origin}/{name} lacks operation_types"
            assert all(isinstance(operation, str) and operation for operation in operations)
            assert not any(
                operation.startswith(prefix)
                for operation in operations
                for prefix in SEMANTIC_OPERATION_PREFIXES
            ), f"{origin}/{name} operation_types contain semantic feature paths"


@pytest.mark.parametrize("origin", ORIGINS)
def test_server_filters_are_physical_parameter_names(origin):
    endpoints = load(origin, "endpoints.yaml")["endpoints"]
    for name, endpoint in endpoints.items():
        params = endpoint.get("params", {})
        for server_filter in endpoint.get("server_filters", []):
            assert server_filter in params, f"{origin}/{name}: {server_filter!r} is not a physical param"
            if "." in server_filter:
                assert server_filter in params  # A dot is allowed only when literally present in the API key.


@pytest.mark.parametrize("origin", ORIGINS)
def test_endpoint_output_matches_payload_root_cardinality(origin):
    endpoints = load(origin, "endpoints.yaml")["endpoints"]
    payloads = load(origin, "mappings.yaml")["payloads"]
    for name, endpoint in endpoints.items():
        output_type = endpoint.get("output", {}).get("type")
        payload = payloads.get(name)
        if payload and output_type in {"object", "binary"}:
            justified = "root_list_exception" in str(endpoint.get("note", ""))
            assert payload["path"] != "[]" or justified, (
                f"{origin}/{name} declares {output_type} but has a list payload root"
            )


def test_get_stamps_payload_roots_match_audited_return_shapes():
    assert load("lsst", "mappings.yaml")["payloads"]["get_stamps"]["path"] == "."
    assert load("lsst", "endpoints.yaml")["endpoints"]["get_stamps"]["output"]["type"] == "object"
    assert load("ztf", "mappings.yaml")["payloads"]["get_stamps"]["path"] == "[]"
    assert load("ztf", "endpoints.yaml")["endpoints"]["get_stamps"]["output"]["type"] == "array"
