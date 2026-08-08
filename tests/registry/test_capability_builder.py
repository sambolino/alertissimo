import yaml

from alertissimo.core.brokers.registry.capability_builder import build_capabilities, registry_directories


def test_builder_runs_for_every_registry():
    for directory in registry_directories():
        result = build_capabilities(directory)
        assert result["broker"] and result["origin"]
        assert yaml.safe_load((directory / "capabilities.generated.yaml").read_text()) == result


def test_inactive_sources_do_not_claim_runtime_capability():
    result = build_capabilities(next(registry_directories("alerce", "lsst")))
    for field in result["semantic_fields"].values():
        if field["source_status"] == "declared_only" or field["endpoint_status"] == "known_unsupported":
            assert field["active"] is False

