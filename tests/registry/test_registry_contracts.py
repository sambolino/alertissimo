from pathlib import Path

import yaml

from alertissimo.core.brokers.registry.capability_builder import REGISTRY_ROOT, registry_directories


def test_six_registry_contracts_parse_and_link():
    directories = list(registry_directories())
    assert len(directories) == 6
    for directory in directories:
        endpoints = yaml.safe_load((directory / "endpoints.yaml").read_text())
        mappings = yaml.safe_load((directory / "mappings.yaml").read_text())
        assert "provides" not in (directory / "endpoints.yaml").read_text()
        assert "output_type" not in (directory / "endpoints.yaml").read_text()
        for endpoint in endpoints["endpoints"].values():
            assert {"transport", "output", "capabilities", "enabled", "status"} <= endpoint.keys()
        for source in mappings["sources"].values():
            assert set(source["endpoints"]) <= set(endpoints["endpoints"])


def test_required_audit_artifacts_exist():
    assert (REGISTRY_ROOT / "unmapped_fields.yaml").is_file()
    assert (REGISTRY_ROOT / "mapping_refactor_report.md").is_file()

