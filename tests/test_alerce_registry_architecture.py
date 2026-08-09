from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
REGISTRY = ROOT / "alertissimo/core/brokers/registry/alerce"
ORIGINS = ("lsst", "ztf")
NESTED = {
    "query_lightcurve.detections": "detections[]",
    "query_lightcurve.non_detections": "non_detections[]",
    "query_lightcurve.forced_photometry": "forced_photometry[]",
}
FORBIDDEN_ENDPOINT_KEYS = {
    "input", "value_from", "binding", "required_inputs", "optional_inputs", "capabilities"
}


def load(origin, filename):
    return yaml.safe_load((REGISTRY / origin / filename).read_text())


def walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_keys(child)


def test_payload_roots_follow_endpoint_output_shapes():
    for origin in ORIGINS:
        endpoints = load(origin, "endpoints.yaml")["endpoints"]
        payloads = load(origin, "mappings.yaml")["payloads"]
        for name, payload in payloads.items():
            if name in NESTED:
                continue
            output_type = endpoints[payload["endpoint"]]["output"]["type"]
            expected = "[]" if output_type == "array" else "."
            assert payload["path"] == expected, (origin, name, output_type)


def test_lightcurve_payloads_are_named_nested_row_collections():
    for origin in ORIGINS:
        payloads = load(origin, "mappings.yaml")["payloads"]
        for name, path in NESTED.items():
            assert payloads[name]["endpoint"] == "query_lightcurve"
            assert payloads[name]["path"] == path


def test_endpoint_contracts_remain_physical_only():
    for origin in ORIGINS:
        endpoints = load(origin, "endpoints.yaml")["endpoints"]
        assert not (set(walk_keys(endpoints)) & FORBIDDEN_ENDPOINT_KEYS)
        for name, endpoint in endpoints.items():
            if endpoint["enabled"]:
                assert endpoint["operation_types"], (origin, name)
            for parameter, definition in endpoint.get("params", {}).items():
                assert definition.get("description"), (origin, name, parameter)
            physical_params = set(endpoint.get("params", {}))
            assert set(endpoint["server_filters"]) <= physical_params


def test_no_planner_terms_registry_was_added():
    assert not list(ROOT.rglob("planner_terms.yaml"))
