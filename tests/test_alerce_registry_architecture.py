from pathlib import Path

import yaml


REGISTRY = Path("alertissimo/core/brokers/registry/alerce")
ORIGINS = ("lsst", "ztf")
ROW_PAYLOADS = {
    "detection": "query_lightcurve.detections",
    "forced_photometry": "query_lightcurve.forced_photometry",
    "non_detection": "query_lightcurve.non_detections",
}
FORBIDDEN_ENDPOINT_KEYS = {
    "input",
    "value_from",
    "binding",
    "required_inputs",
    "optional_inputs",
    "capabilities",
}


def _load(origin: str, filename: str) -> dict:
    with (REGISTRY / origin / filename).open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def _walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def test_lightcurve_rows_use_nested_payloads():
    for origin in ORIGINS:
        document = _load(origin, "mappings.yaml")
        for record, payload in ROW_PAYLOADS.items():
            prefix = f"{record}@{origin}:alerce."
            references = [
                reference
                for semantic_path, mapped in document["mappings"].items()
                if semantic_path.startswith(prefix)
                for reference in mapped
            ]
            assert references
            assert not any(reference.startswith("query_lightcurve#") for reference in references)
            assert any(reference.startswith(f"{payload}#") for reference in references)

        all_references = [
            reference
            for mapped in document["mappings"].values()
            for reference in mapped
        ]
        assert not any(
            marker in reference
            for reference in all_references
            for marker in ("#detections.", "#forced_photometry.", "#non_detections.")
        )


def test_lightcurve_payloads_are_row_collections():
    expected = {
        "query_lightcurve.detections": "detections[]",
        "query_lightcurve.forced_photometry": "forced_photometry[]",
        "query_lightcurve.non_detections": "non_detections[]",
    }
    for origin in ORIGINS:
        payloads = _load(origin, "mappings.yaml")["payloads"]
        for name, path in expected.items():
            assert payloads[name] == {"endpoint": "query_lightcurve", "path": path}


def test_endpoint_contracts_keep_physical_described_parameters():
    for origin in ORIGINS:
        document = _load(origin, "endpoints.yaml")
        assert FORBIDDEN_ENDPOINT_KEYS.isdisjoint(_walk_keys(document))
        for endpoint in document["endpoints"].values():
            for parameter in endpoint.get("params", {}).values():
                assert parameter.get("description")
            server_filters = endpoint.get("server_filters", [])
            assert set(server_filters) <= set(endpoint.get("params", {}))

