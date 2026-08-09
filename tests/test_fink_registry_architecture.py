"""Architecture invariants for the minimal Fink registry."""
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1] / "alertissimo/core/brokers/registry/fink"
ORIGINS = ("lsst", "ztf")
ROOTS = (
    "summary", "detection", "forced_photometry", "data_product",
    "classification", "crossmatch", "survey",
)
FORBIDDEN_PATH_PARTS = (
    "image_metrics", "reference.nearest_source", "classification@fink",
    ".classifier.", ".raw.",
)
FORBIDDEN_MAPPING_KEYS = {
    "field", "availability", "sources", "source_fields", "field_status",
    "endpoints", "record_type", "object_summary", "capabilities",
}


def load(origin, filename):
    return yaml.safe_load((ROOT / origin / filename).read_text())


def refs(document):
    return {ref for values in document["mappings"].values() for ref in values}


def unmapped_refs(document):
    return {next(iter(entry)) for entry in document["unmapped"]}


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def test_mappings_use_minimal_payload_reference_schema():
    for origin in ORIGINS:
        document = load(origin, "mappings.yaml")
        assert not (set(document) & FORBIDDEN_MAPPING_KEYS)
        for values in document["mappings"].values():
            assert isinstance(values, list) and values
            assert all(isinstance(value, str) and value.count("#") == 1 for value in values)


def test_semantic_paths_are_catalog_compatible_and_producer_qualified():
    for origin in ORIGINS:
        expected = tuple(f"{root}@{origin}:fink" for root in ROOTS)
        for path in load(origin, "mappings.yaml")["mappings"]:
            assert path.startswith(expected), path
            assert not any(part in path for part in FORBIDDEN_PATH_PARTS), path


def test_unmapped_is_real_and_disjoint_from_mappings():
    for origin in ORIGINS:
        mappings = load(origin, "mappings.yaml")
        unmapped = load(origin, "unmapped_fields.yaml")
        assert unmapped["unmapped"], origin
        assert refs(mappings).isdisjoint(unmapped_refs(unmapped))


def test_unmapped_refs_use_declared_payloads_and_keep_colon_fields_valid():
    saw_colon = False
    for origin in ORIGINS:
        mappings = load(origin, "mappings.yaml")
        declared = set(mappings["payloads"])
        for reference in refs(mappings) | unmapped_refs(load(origin, "unmapped_fields.yaml")):
            payload, raw = reference.split("#", 1)
            assert payload in declared
            assert raw
            saw_colon |= ":" in raw
    assert saw_colon


def test_cutouts_remain_data_product_paths():
    for origin in ORIGINS:
        mappings = load(origin, "mappings.yaml")
        cutout_refs = {ref for ref in refs(mappings) if ref.startswith("cutouts#")}
        assert cutout_refs
        for path, path_refs in mappings["mappings"].items():
            if cutout_refs.intersection(path_refs):
                assert path.startswith(f"data_product@{origin}:fink"), path


def test_endpoints_are_physical_and_promoted_metadata_is_retained():
    for origin in ORIGINS:
        document = load(origin, "endpoints.yaml")
        assert any("operation_types" in endpoint for endpoint in document["endpoints"].values())
        for node in walk(document):
            assert not ({"binding", "input", "value_from", "capabilities"} & set(node))
        for endpoint in document["endpoints"].values():
            projection = endpoint.get("projection")
            if projection:
                assert set(projection) <= {"supports_columns", "param"}
                if projection.get("supports_columns"):
                    assert projection.get("param") in endpoint.get("params", {})
