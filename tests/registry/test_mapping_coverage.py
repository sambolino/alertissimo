from pathlib import Path

import yaml

from alertissimo.core.brokers.registry.capability_builder import build_report


ROOT = Path(__file__).parents[2] / "alertissimo/core/brokers/registry"
TARGETS = (("alerce", "lsst"), ("alerce", "ztf"), ("fink", "lsst"), ("fink", "ztf"))


def test_every_source_field_is_accounted_for():
    report = build_report(ROOT)
    for broker, origin in TARGETS:
        counts = report["brokers"][f"{broker}/{origin}"]
        assert counts["missing"] == 0
        assert counts["preserved"] == counts["mapped"] + counts["unmapped"]


def test_mapping_files_use_grouped_structure():
    for broker, origin in TARGETS:
        document = yaml.safe_load((ROOT / broker / origin / "mappings.yaml").read_text())
        assert document["sources"]
        assert document["mappings"]
        assert "attribute_inventory" not in document


def test_alerce_lsst_photometry_sources_have_semantic_or_unmapped_coverage():
    mapping_path = ROOT / "alerce/lsst/mappings.yaml"
    document = yaml.safe_load(mapping_path.read_text())
    unmapped = yaml.safe_load(mapping_path.with_name("unmapped_fields.yaml").read_text())
    mapped_pairs = set()
    for mapping in document["mappings"].values():
        for source in mapping.get("sources", []):
            mapped_pairs.add((source["endpoint"], source["field"]))
        endpoints = mapping.get("endpoints", [])
        if mapping.get("field"):
            mapped_pairs.update((endpoint, mapping["field"]) for endpoint in endpoints)
    unmapped_pairs = {(item["method"], item["field"]) for item in unmapped["unmapped_fields"]}
    required = {"query_detections", "query_forced_photometry", "query_lightcurve", "query_non_detections"}
    for endpoint in required:
        raw = {(item["method"], item["field"]) for item in document["sources"] if item["method"] == endpoint}
        assert raw
        assert raw <= mapped_pairs | unmapped_pairs
