"""Conservative validation for the ordered semantic-catalog DSL."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import yaml

ROOT = Path(__file__).parent
FORBIDDEN = {"classifier", "magstats", "features", "schema", "metadata"}
RECORDS = {"summary", "detection", "classification", "lightcurve", "crossmatch", "data_product", "survey"}


def iter_paths(document: dict) -> Iterable[tuple[str, bool]]:
    for group, spec in document.get("mappings", {}).items():
        record = spec.get("record", group).split("@", 1)[0]
        for path in spec.get("fields", {}):
            yield f"{record}.{path}", False
    for path, spec in document.get("dynamic", {}).items():
        record = path.split("@", 1)[0]
        suffix = path.split(":", 1)[-1].split(".", 1)[-1]
        yield f"{record}.{suffix}", spec.get("status") == "raw_extension"


def validate_document(document: dict, catalog_text: str) -> list[str]:
    """Return errors without claiming to fully parse the catalog DSL."""
    declared = set(re.findall(r"^<(\w+)>:", catalog_text, re.MULTILINE))
    errors = []
    for path, raw_extension in iter_paths(document):
        parts = path.split(".")
        if parts[0] not in RECORDS and parts[0] not in declared:
            errors.append(f"invented record type: {path}")
        if any(part in FORBIDDEN for part in parts):
            errors.append(f"forbidden semantic branch: {path}")
        if "properties" in parts and not raw_extension:
            errors.append(f"properties is only allowed for raw extensions: {path}")
    return errors


def validate_file(path: Path) -> list[str]:
    return validate_document(yaml.safe_load(path.read_text()), (ROOT / "feature_catalog.yaml").read_text())


def main() -> int:
    errors = [f"{p}: {e}" for p in ROOT.glob("*/*/mappings.yaml") for e in validate_file(p)]
    print("\n".join(errors) if errors else "semantic path guardrails passed")
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
