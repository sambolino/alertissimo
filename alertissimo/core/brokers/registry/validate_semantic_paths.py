"""Conservative guardrails for semantic paths in registry mappings."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

FORBIDDEN_BRANCHES = {"classifier", "magstats", "features", "schema", "metadata"}


def load_catalog(path: Path | str) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


def _matches(node: Any, parts: list[str]) -> bool:
    if not parts:
        return True
    if not isinstance(node, dict):
        return False
    part = parts[0]
    candidates = [part]
    candidates.extend(key for key in node if isinstance(key, str) and key.startswith("{") and key.endswith("}"))
    return any(candidate in node and _matches(node[candidate], parts[1:]) for candidate in candidates)


def validate_semantic_path(
    record: str, path: str, catalog: dict[str, Any], *, dynamic: bool = False, broker: str | None = None
) -> list[str]:
    """Return warnings for a path; validation never mutates registry files."""
    first = path.split(".", 1)[0]
    if first in FORBIDDEN_BRANCHES:
        return [f"forbidden semantic branch: {first}.*"]
    records = catalog.get("records", {})
    if record not in records:
        return [f"unknown portfolio record: {record}"]
    if dynamic:
        allowed = broker == "antares" and ("properties.{field}" in path or "catalog_objects.{catalog}.{field}" in path)
        return [] if allowed else [f"dynamic/raw extension is not permitted: {record}.{path}"]
    if not _matches(records[record], path.split(".")):
        return [f"path is not present in feature catalog: {record}.{path}"]
    return []


def validate_mapping_document(document: dict[str, Any], catalog: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for portfolio, mapping in (document.get("mappings") or {}).items():
        record = portfolio.split("@", 1)[0]
        for path in (mapping.get("fields") or {}):
            warnings.extend(validate_semantic_path(record, path, catalog, broker=document.get("broker")))
    for full_path, mapping in (document.get("dynamic") or {}).items():
        record, path = full_path.split("@", 1)[0], full_path.split(":", 1)[1]
        warnings.extend(validate_semantic_path(record, path, catalog, dynamic=True, broker=document.get("broker")))
        if mapping.get("status") != "raw_extension":
            warnings.append(f"dynamic mapping is not marked raw_extension: {full_path}")
    return warnings


def main(argv: list[str] | None = None) -> int:
    """Print conservative warnings for selected mapping documents."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="mappings.yaml files (all registries by default)")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent
    paths = args.paths or sorted(root.glob("*/*/mappings.yaml"))
    catalog = load_catalog(root / "feature_catalog.yaml")
    warning_count = 0
    for path in paths:
        with path.open(encoding="utf-8") as stream:
            document = yaml.safe_load(stream) or {}
        for warning in validate_mapping_document(document, catalog):
            warning_count += 1
            print(f"{path}: warning: {warning}")
    if not warning_count:
        print(f"validated {len(paths)} mapping file(s); no warnings")
    # Guardrails deliberately warn rather than making destructive or brittle
    # first-pass validation a failing operation.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
