import yaml

from alertissimo.core.brokers.registry.capability_builder import REGISTRY_ROOT, registry_directories
from alertissimo.core.brokers.registry.validate_semantic_paths import load_catalog, validate_mapping_document, validate_semantic_path


def test_human_mappings_pass_catalog_guardrails():
    catalog = load_catalog(REGISTRY_ROOT / "feature_catalog.yaml")
    for directory in registry_directories():
        document = yaml.safe_load((directory / "mappings.yaml").read_text())
        assert validate_mapping_document(document, catalog) == []


def test_forbidden_branches_are_flagged():
    catalog = load_catalog(REGISTRY_ROOT / "feature_catalog.yaml")
    assert validate_semantic_path("classification", "classifier.name", catalog)
    assert validate_semantic_path("summary", "magstats.mean", catalog)

