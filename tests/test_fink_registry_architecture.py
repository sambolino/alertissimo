from pathlib import Path

import pytest
import yaml

from alertissimo.core.brokers.registry.mapping_schema import validate_mapping_file


ROOT = Path(__file__).parents[1] / "alertissimo/core/brokers/registry/fink"
ORIGINS = ("lsst", "ztf")
FORBIDDEN_ENDPOINT_KEYS = {
    "input",
    "value_from",
    "binding",
    "required_inputs",
    "optional_inputs",
    "required_bindings",
    "optional_bindings",
    "one_of_bindings",
    "capabilities",
    "record_scope",
    "returns_science_data",
}
LEGACY_MAPPING_KEYS = {
    "field",
    "availability",
    "sources",
    "source_fields",
    "field_status",
    "endpoints",
    "record_type",
}


def load(origin, filename):
    return yaml.safe_load((ROOT / origin / filename).read_text(encoding="utf-8"))


@pytest.mark.parametrize("origin", ORIGINS)
def test_endpoints_are_physical_contracts(origin):
    endpoints = load(origin, "endpoints.yaml")["endpoints"]
    for endpoint_name, endpoint in endpoints.items():
        assert endpoint.get("operation_types"), endpoint_name
        assert all("@" not in label and "." not in label for label in endpoint["operation_types"])

        params = endpoint.get("params", {})
        for parameter_name, parameter in params.items():
            assert parameter.get("description", "").strip(), (endpoint_name, parameter_name)
        assert set(endpoint.get("server_filters", ())) <= set(params)

        projection = endpoint.get("projection", {})
        if projection.get("supports_columns"):
            parameter_name = projection["param"]
            assert parameter_name in params
            assert params[parameter_name].get("role") == "projection"

        stack = [endpoint]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                assert FORBIDDEN_ENDPOINT_KEYS.isdisjoint(value), endpoint_name
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)


def test_fink_has_no_planner_terms_registry():
    assert not list(ROOT.rglob("planner_terms.yaml"))


@pytest.mark.parametrize("origin", ORIGINS)
def test_minimal_mapping_schema_and_payload_roots(origin):
    mapping_path = ROOT / origin / "mappings.yaml"
    validate_mapping_file(mapping_path)
    document = load(origin, "mappings.yaml")
    endpoints = load(origin, "endpoints.yaml")["endpoints"]
    payloads = document["payloads"]

    assert payloads
    assert document["mappings"]
    for payload, definition in payloads.items():
        endpoint_name = definition.get("endpoint", payload)
        assert endpoint_name in endpoints
        output_type = endpoints[endpoint_name]["output"]["type"]
        assert definition["path"] == ("[]" if output_type == "array" else ".")

    for semantic_path, references in document["mappings"].items():
        assert LEGACY_MAPPING_KEYS.isdisjoint(references if isinstance(references, dict) else {})
        assert isinstance(references, list) and references
        assert ".raw." not in semantic_path
        assert ".classifier." not in semantic_path
        assert "classification.classifier" not in semantic_path
        for reference in references:
            payload, raw_field = reference.split("#", 1)
            assert payload in payloads
            assert raw_field


@pytest.mark.parametrize("origin", ORIGINS)
def test_mapped_and_unmapped_references_are_disjoint(origin):
    mappings = load(origin, "mappings.yaml")["mappings"]
    unmapped = load(origin, "unmapped_fields.yaml")["unmapped"]
    mapped_refs = {reference for references in mappings.values() for reference in references}
    unmapped_refs = {next(iter(entry)) for entry in unmapped}
    assert mapped_refs.isdisjoint(unmapped_refs)


def test_colons_are_preserved_in_raw_fink_fields():
    lsst = load("lsst", "mappings.yaml")["mappings"]
    ztf = load("ztf", "mappings.yaml")["mappings"]
    assert "objects#r:diaObjectId" in lsst["summary@lsst:fink.identity.object_id"]
    assert "objects#i:objectId" in ztf["summary@ztf:fink.identity.object_id"]


@pytest.mark.parametrize("origin", ORIGINS)
def test_cutouts_use_data_product_semantics(origin):
    mappings = load(origin, "mappings.yaml")["mappings"]
    cutouts = {path: refs for path, refs in mappings.items() if any(ref.startswith("cutouts#") for ref in refs)}
    assert cutouts
    assert set(cutouts) == {
        f"data_product@{origin}:fink.cutout.science",
        f"data_product@{origin}:fink.cutout.template",
        f"data_product@{origin}:fink.cutout.difference",
    }
