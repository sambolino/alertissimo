"""Build derived broker capabilities from human-authored registry YAML."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any, Iterable

import yaml

from .validate_semantic_paths import load_catalog, validate_mapping_document

REGISTRY_ROOT = Path(__file__).resolve().parent
BROKERS = ("fink", "alerce", "antares")
ORIGINS = ("ztf", "lsst")


def _read(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def registry_directories(broker: str | None = None, origin: str | None = None) -> Iterable[Path]:
    for broker_name in BROKERS:
        for origin_name in ORIGINS:
            if (broker is None or broker == broker_name) and (origin is None or origin == origin_name):
                directory = REGISTRY_ROOT / broker_name / origin_name
                if directory.is_dir():
                    yield directory


def build_capabilities(directory: Path | str) -> dict[str, Any]:
    directory = Path(directory)
    endpoint_path, mapping_path = directory / "endpoints.yaml", directory / "mappings.yaml"
    catalog_path = REGISTRY_ROOT / "feature_catalog.yaml"
    endpoint_doc, mapping_doc = _read(endpoint_path), _read(mapping_path)
    catalog = load_catalog(catalog_path)
    warnings = validate_mapping_document(mapping_doc, catalog)
    if warnings:
        raise ValueError("semantic path validation failed:\n" + "\n".join(warnings))
    endpoints = endpoint_doc.get("endpoints", {})
    result: dict[str, Any] = {
        "broker": mapping_doc["broker"], "origin": mapping_doc["origin"],
        "generated_from": {"endpoints_sha256": _digest(endpoint_path), "mappings_sha256": _digest(mapping_path), "feature_catalog_sha256": _digest(catalog_path)},
        "semantic_fields": {}, "endpoints": {},
    }
    endpoint_fields: dict[str, list[str]] = {name: [] for name in endpoints}
    sources = mapping_doc.get("sources", {})
    for portfolio, mapping in mapping_doc.get("mappings", {}).items():
        source_name = mapping["source"]
        if source_name not in sources:
            raise ValueError(f"unknown mapping source: {source_name}")
        source = sources[source_name]
        linked = source.get("endpoints", [])
        missing = set(linked) - set(endpoints)
        if missing:
            raise ValueError(f"source {source_name} references unknown endpoints: {sorted(missing)}")
        for semantic_path, specification in mapping.get("fields", {}).items():
            full_path = f"{portfolio}.{semantic_path}"
            statuses = [endpoints[name].get("status") for name in linked]
            active = bool(linked) and all(endpoints[name].get("enabled") and endpoints[name].get("status") == "enabled" for name in linked)
            active = active and source.get("status") != "declared_only" and source.get("live_status") != "empty_in_sampling"
            result["semantic_fields"][full_path] = {"source": source_name, "raw_field": specification["field"], "endpoints": linked, "endpoint_status": statuses[0] if len(set(statuses)) == 1 else statuses, "source_status": source.get("status"), "active": active, "dynamic": "{" in semantic_path}
            for name in linked:
                endpoint_fields[name].append(full_path)
    for full_path, specification in mapping_doc.get("dynamic", {}).items():
        source_name, source = specification["source"], sources[specification["source"]]
        linked = source.get("endpoints", [])
        if set(linked) - set(endpoints):
            raise ValueError(f"dynamic source {source_name} references unknown endpoint")
        result["semantic_fields"][full_path] = {"source": source_name, "raw_field": specification["field"], "endpoints": linked, "endpoint_status": "enabled", "source_status": source.get("status"), "active": all(endpoints[name].get("enabled") for name in linked), "dynamic": True, "status": "raw_extension"}
        for name in linked:
            endpoint_fields[name].append(full_path)
    for name, endpoint in endpoints.items():
        caps = endpoint.get("capabilities", {})
        result["endpoints"][name] = {"enabled": endpoint["enabled"], "status": endpoint["status"], "operation_types": caps.get("operation_types", []), "record_scope": caps.get("record_scope", []), "required_bindings": caps.get("required_bindings", []), "semantic_fields": sorted(endpoint_fields[name])}
    return result


def write_capabilities(directory: Path | str) -> Path:
    directory = Path(directory)
    output = directory / "capabilities.generated.yaml"
    output.write_text(yaml.safe_dump(build_capabilities(directory), sort_keys=False), encoding="utf-8")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--broker", choices=BROKERS)
    parser.add_argument("--origin", choices=ORIGINS)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    for directory in registry_directories(args.broker, args.origin):
        if args.write:
            print(write_capabilities(directory))
        else:
            print(yaml.safe_dump(build_capabilities(directory), sort_keys=False), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
