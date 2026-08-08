"""Generate runtime capability indexes from human-maintained registry files."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import yaml

from .validate_semantic_paths import validate_document

ROOT = Path(__file__).parent


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(broker: str, origin: str) -> dict:
    directory = ROOT / broker / origin
    endpoint_path, mapping_path = directory / "endpoints.yaml", directory / "mappings.yaml"
    endpoints_doc = yaml.safe_load(endpoint_path.read_text())
    mappings_doc = yaml.safe_load(mapping_path.read_text())
    catalog_text = (ROOT / "feature_catalog.yaml").read_text()
    errors = validate_document(mappings_doc, catalog_text)
    if errors:
        raise ValueError("; ".join(errors))
    endpoints = endpoints_doc["endpoints"]
    semantic_fields: dict[str, dict] = {}
    endpoint_fields = {name: [] for name in endpoints}
    for group, mapping in mappings_doc.get("mappings", {}).items():
        source_name = mapping["source"]
        source = mappings_doc["sources"][source_name]
        missing = set(source["endpoints"]) - set(endpoints)
        if missing:
            raise ValueError(f"source {source_name} references unknown endpoints: {sorted(missing)}")
        record = mapping.get("record", group)
        for semantic, raw in mapping.get("fields", {}).items():
            full = f"{record}.{semantic}"
            statuses = [endpoints[name]["status"] for name in source["endpoints"]]
            active = (source.get("status") != "declared_only" and source.get("live_status") != "empty_in_sampling"
                      and all(endpoints[name]["enabled"] and endpoints[name]["status"] != "known_unsupported" for name in source["endpoints"]))
            semantic_fields[full] = {"source": source_name, "raw_field": raw["field"], "endpoints": source["endpoints"],
                "endpoint_status": statuses[0] if len(set(statuses)) == 1 else statuses, "source_status": source["status"],
                "active": active, "dynamic": "{" in semantic}
            for name in source["endpoints"]: endpoint_fields[name].append(full)
    for full, spec in mappings_doc.get("dynamic", {}).items():
        source = mappings_doc["sources"][spec["source"]]
        semantic_fields[full] = {"source": spec["source"], "raw_field": spec["field"], "endpoints": source["endpoints"],
            "endpoint_status": "enabled", "source_status": source["status"], "active": True,
            "dynamic": True, "raw_extension": True}
        for name in source["endpoints"]: endpoint_fields[name].append(full)
    generated_endpoints = {}
    for name, endpoint in endpoints.items():
        cap = endpoint["capabilities"]
        generated_endpoints[name] = {"enabled": endpoint["enabled"], "status": endpoint["status"],
            "operation_types": cap["operation_types"], "record_scope": cap["record_scope"],
            "required_bindings": cap["required_bindings"], "semantic_fields": sorted(endpoint_fields[name])}
    return {"broker": broker, "origin": origin, "generated_from": {"endpoints_sha256": _digest(endpoint_path),
        "mappings_sha256": _digest(mapping_path), "feature_catalog_sha256": _digest(ROOT / "feature_catalog.yaml")},
        "semantic_fields": semantic_fields, "endpoints": generated_endpoints}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--broker"); parser.add_argument("--origin"); parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    targets = [(b.name, o.name) for b in ROOT.iterdir() if b.is_dir() and b.name in {"fink", "alerce", "antares"} for o in b.iterdir() if o.name in {"ztf", "lsst"}]
    if args.broker: targets = [x for x in targets if x[0] == args.broker]
    if args.origin: targets = [x for x in targets if x[1] == args.origin]
    for broker, origin in sorted(targets):
        result = build(broker, origin)
        if args.write: (ROOT / broker / origin / "capabilities.generated.yaml").write_text(yaml.safe_dump(result, sort_keys=False))
        else: print(yaml.safe_dump(result, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
