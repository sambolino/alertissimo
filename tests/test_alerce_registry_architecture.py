from pathlib import Path

import yaml


ROOT = Path("alertissimo/core")
ALERCE = ROOT / "brokers/registry/alerce"
ALLOWED_INPUTS = {
    "object_id", "source_id", "cone.ra", "cone.dec", "cone.radius",
    "time.start", "time.end", "classifier", "class_name", "limit",
    "columns", "format",
}


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_alerce_endpoints_are_call_contracts_not_semantic_mappings():
    for path in ALERCE.glob("*/endpoints.yaml"):
        document = load(path)
        assert "binding:" not in path.read_text(encoding="utf-8")
        for endpoint in document["endpoints"].values():
            assert "capabilities" not in endpoint
            assert set(endpoint.get("required_inputs", [])) <= ALLOWED_INPUTS
            assert set(endpoint.get("optional_inputs", [])) <= ALLOWED_INPUTS
            for parameter in endpoint.get("parameters", {}).values():
                if "input" in parameter:
                    assert parameter["input"] in ALLOWED_INPUTS


def test_planner_terms_are_input_nouns_only():
    terms = load(ROOT / "dsl/planner_terms.yaml")["terms"]
    forbidden = {"query_probabilities", "query_detections", "magpsf", "diaObjectId"}
    assert terms
    for canonical, definition in terms.items():
        assert definition["kind"] == "input"
        assert isinstance(definition["synonyms"], list) and definition["synonyms"]
        assert canonical not in forbidden
