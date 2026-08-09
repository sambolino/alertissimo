from pathlib import Path

import pytest
import yaml


REGISTRY = Path("alertissimo/core/brokers/registry/alerce")
ENDPOINT_FILES = [REGISTRY / survey / "endpoints.yaml" for survey in ("lsst", "ztf")]
FORBIDDEN_KEYS = {"binding", "input", "value_from", "required_inputs", "optional_inputs", "capabilities"}
SEMANTIC_DESCRIPTION_FRAGMENTS = (
    "summary.", "detection.", "classification.assessment", "classification.best", "data_product.",
)


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


@pytest.mark.parametrize("path", ENDPOINT_FILES)
def test_endpoints_are_physical_api_contracts(path):
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    for mapping in walk(document):
        assert FORBIDDEN_KEYS.isdisjoint(mapping), f"forbidden endpoint keys in {path}: {FORBIDDEN_KEYS & mapping.keys()}"

    for endpoint_name, endpoint in document["endpoints"].items():
        parameters = endpoint.get("params", {})
        for parameter_name, metadata in parameters.items():
            description = metadata.get("description")
            assert isinstance(description, str) and description.strip(), f"{endpoint_name}.{parameter_name} needs a description"
            assert not any(fragment in description for fragment in SEMANTIC_DESCRIPTION_FRAGMENTS)
        for parameter_name in endpoint.get("server_filters", []):
            assert parameter_name in parameters, f"{endpoint_name} filter {parameter_name!r} is not a physical parameter"


def test_planner_terms_registry_is_absent():
    assert not Path("alertissimo/core/dsl/planner_terms.yaml").exists()
