from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).parents[1] / "alertissimo/core/brokers/registry/fink"
ORIGINS = ("lsst", "ztf")


def load(origin, filename):
    return yaml.safe_load((ROOT / origin / filename).read_text())


@pytest.mark.parametrize("origin", ORIGINS)
def test_payload_roots_match_endpoint_output_shape(origin):
    endpoints = load(origin, "endpoints.yaml")["endpoints"]
    payloads = load(origin, "mappings.yaml")["payloads"]

    for payload_name, payload in payloads.items():
        endpoint_name = payload.get("endpoint", payload_name)
        output_type = endpoints[endpoint_name]["output"]["type"]
        expected = "[]" if output_type == "array" else "."
        assert payload["path"] == expected, (origin, payload_name, output_type)

    assert all(payload["path"] != "$" for payload in payloads.values())


@pytest.mark.parametrize("origin", ORIGINS)
def test_mappings_use_qualified_semantics_and_payload_references(origin):
    document = load(origin, "mappings.yaml")
    payloads = document["payloads"]
    for semantic_path, references in document["mappings"].items():
        assert "@" in semantic_path
        assert "image_metrics" not in semantic_path
        assert "reference.nearest_source" not in semantic_path
        assert "classification@fink" not in semantic_path
        assert ".classifier." not in semantic_path
        assert ".raw." not in semantic_path
        for reference in references:
            payload, separator, field = reference.partition("#")
            assert separator and field
            assert payload in payloads


@pytest.mark.parametrize("origin", ORIGINS)
def test_unmapped_is_nonempty_and_disjoint(origin):
    mappings = load(origin, "mappings.yaml")["mappings"]
    unmapped = load(origin, "unmapped_fields.yaml")["unmapped"]
    assert unmapped
    mapped_refs = {ref for refs in mappings.values() for ref in refs}
    unmapped_refs = {next(iter(entry)) for entry in unmapped}
    assert mapped_refs.isdisjoint(unmapped_refs)


@pytest.mark.parametrize("origin", ORIGINS)
def test_cutouts_are_data_products(origin):
    mappings = load(origin, "mappings.yaml")["mappings"]
    cutout_paths = [
        path for path, refs in mappings.items()
        if any(ref.startswith("cutouts#") for ref in refs)
    ]
    assert cutout_paths
    assert all(path.startswith("data_product@") for path in cutout_paths)


@pytest.mark.parametrize("origin", ORIGINS)
def test_endpoints_remain_physical_contracts(origin):
    endpoints = load(origin, "endpoints.yaml")["endpoints"]
    forbidden = {"binding", "input", "value_from", "capabilities"}
    for endpoint in endpoints.values():
        assert endpoint.get("operation_types")
        assert set(endpoint.get("server_filters", ())) <= set(endpoint.get("params", {}))
        assert "post_filter" in endpoint
        for name, parameter in endpoint.get("params", {}).items():
            assert parameter.get("description"), name
            if parameter.get("role") == "projection":
                assert name == "columns"
        stack = [endpoint]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                assert forbidden.isdisjoint(value)
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
