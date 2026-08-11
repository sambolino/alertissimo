from pathlib import Path

import yaml

from alertissimo.data_layer.semantic_model import SemanticPathModel

ROOT = Path(__file__).parents[1]
REGISTRY = ROOT / "alertissimo/data_layer/providers/alerce/ztf"


def _documents():
    return (
        yaml.safe_load((REGISTRY / "mappings.yaml").read_text()),
        yaml.safe_load((REGISTRY / "endpoints.yaml").read_text()),
        yaml.safe_load((REGISTRY / "unmapped_fields.yaml").read_text()),
    )


def test_every_enabled_endpoint_has_an_explicit_payload_binding():
    mappings, endpoints, _ = _documents()
    enabled = {name for name, spec in endpoints["endpoints"].items() if spec["enabled"]}
    bound = {spec["endpoint"] for spec in mappings["payloads"].values()}
    assert enabled == bound
    assert all("endpoint" in spec for spec in mappings["payloads"].values())


def test_all_alerce_ztf_semantic_paths_are_current_ontology_paths():
    mappings, _, _ = _documents()
    model = SemanticPathModel.from_ontology()
    assert all(model.is_valid(path) for path in mappings["mappings"])


def test_detection_photometry_and_reference_source_use_canonical_containers():
    mappings, _, _ = _documents()
    paths = mappings["mappings"]
    assert "query_detections#magpsf" in paths["detection@ztf:alerce.photometry.{filter}.psf.mag"]
    assert "query_detections#sigmapsf" in paths["detection@ztf:alerce.photometry.{filter}.psf.mag_error"]
    assert "query_detections#diffmaglim" in paths["detection@ztf:alerce.photometry.{filter}.limit.mag"]
    assert "query_lightcurve.detections#ranr" in paths["detection@ztf:alerce.reference_image.nearest_source.position.ra"]
    assert not any("crossmatch.nearest_source" in path for path in paths)


def test_observed_ztf_filter_ids_normalize_to_one_canonical_band_namespace():
    mappings, _, _ = _documents()
    carriers = [
        "detection@ztf:alerce.photometry.{filter}",
    ]
    for path in carriers:
        for transform in mappings["transforms"][path].values():
            assert transform["map"][1] == "g"
            assert transform["map"][2] == "r"
            assert transform["map"][3] == "i"


def test_semantic_debt_has_precise_reasons_and_explanations():
    mappings, _, debt = _documents()
    mapped = {ref for refs in mappings["mappings"].values() for ref in refs}
    entries = {next(iter(entry)): next(iter(entry.values())) for entry in debt["unmapped"]}
    assert mapped.isdisjoint(entries)
    assert all(item["reason"] != "no_stable_feature_catalog_path" for item in entries.values())
    assert all(item.get("candidate_meaning") or item.get("note") for item in entries.values())
