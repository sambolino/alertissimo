"""Validate broker field coverage and build the registry mapping report.

Mapping files deliberately keep source inventories separate from semantic
mappings.  This module verifies that every source field is represented by a
mapping or by the adjacent ``unmapped_fields.yaml`` inventory.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Iterable

import yaml


REGISTRY_ROOT = Path(__file__).parent
REPORT_PATH = REGISTRY_ROOT / "mapping_report.yaml"


def _source_records(document: dict[str, Any]) -> list[dict[str, Any]]:
    sources = document.get("sources", [])
    if isinstance(sources, list):
        return sources
    records: list[dict[str, Any]] = []
    for endpoint, fields in sources.items():
        for item in fields:
            item = {"field": item} if isinstance(item, str) else dict(item)
            item.setdefault("method", endpoint)
            records.append(item)
    return records


def _mapped_pairs(document: dict[str, Any]) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for mapping in document.get("mappings", {}).values():
        if "sources" in mapping:
            result.update(
                (source["endpoint"], source["field"])
                for source in mapping["sources"]
            )
            continue
        field = mapping.get("field")
        endpoints = mapping.get("availability")
        if not isinstance(endpoints, list):
            endpoints = mapping.get("endpoints", [])
        if field and isinstance(endpoints, list):
            result.update((endpoint, field) for endpoint in endpoints)
    return result


def _pairs(records: Iterable[dict[str, Any]]) -> set[tuple[str, str]]:
    return {(record["method"], record["field"]) for record in records}


def build_report(root: Path = REGISTRY_ROOT) -> dict[str, Any]:
    report: dict[str, Any] = {"brokers": {}}
    errors: list[str] = []
    for mapping_path in sorted(root.glob("*/*/mappings.yaml")):
        document = yaml.safe_load(mapping_path.read_text())
        if "sources" not in document or "mappings" not in document:
            continue
        source_pairs = _pairs(_source_records(document))
        mapped_pairs = source_pairs & _mapped_pairs(document)
        unmapped_path = mapping_path.with_name("unmapped_fields.yaml")
        unmapped_document = yaml.safe_load(unmapped_path.read_text()) if unmapped_path.exists() else {}
        unmapped_pairs = source_pairs & _pairs(unmapped_document.get("unmapped_fields", []))
        missing = source_pairs - mapped_pairs - unmapped_pairs
        key = f"{document['broker']}/{document['origin']}"
        report["brokers"][key] = {
            "preserved": len(source_pairs),
            "mapped": len(mapped_pairs),
            "unmapped": len(unmapped_pairs),
            "missing": len(missing),
        }
        if missing:
            preview = ", ".join(f"{endpoint}:{field}" for endpoint, field in sorted(missing)[:5])
            errors.append(f"{key} has {len(missing)} unaccounted source fields ({preview})")
    if errors:
        raise ValueError("\n".join(errors))
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="write mapping_report.yaml")
    args = parser.parse_args()
    report = build_report()
    rendered = yaml.safe_dump(report, sort_keys=False)
    if args.write:
        REPORT_PATH.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
