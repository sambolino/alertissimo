"""Validation helpers for broker ``mappings.yaml`` files."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Mapping

import yaml


ALLOWED_TOP_LEVEL_KEYS = {
    "broker",
    "origin",
    "payloads",
    "mappings",
    "description",
    "notes",
}


def validate_mapping_data(data: Any) -> None:
    """Validate the minimal shape of a broker mapping document.

    ``ValueError`` is raised at the first schema violation.  References are
    deliberately kept raw here: interpreting their contents belongs to the
    mapping consumer rather than this structural validator.
    """
    if not isinstance(data, Mapping):
        raise ValueError("mapping document must be an object")

    unknown_keys = set(data) - ALLOWED_TOP_LEVEL_KEYS
    if unknown_keys:
        names = ", ".join(sorted(str(key) for key in unknown_keys))
        raise ValueError(f"unknown top-level key(s): {names}")

    for field in ("broker", "origin"):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")

    for field in ("description", "notes"):
        if field in data and not isinstance(data[field], str):
            raise ValueError(f"{field} must be a string")

    mappings = data.get("mappings")
    if not isinstance(mappings, Mapping):
        raise ValueError("mappings must be an object")

    for feature_id, references in mappings.items():
        if not isinstance(references, list) or not references:
            raise ValueError(
                f"mapping {feature_id!r} must be a non-empty list of raw references"
            )


def _mapping_files(registry_root: Path) -> list[Path]:
    return sorted(registry_root.glob("*/*/mappings.yaml"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--all", action="store_true", help="validate every broker mapping")
    args = parser.parse_args(argv)

    if args.all and args.paths:
        parser.error("paths cannot be combined with --all")
    if not args.all and not args.paths:
        parser.error("provide mapping paths or --all")

    paths = _mapping_files(Path(__file__).parent) if args.all else args.paths
    failures = 0
    for path in paths:
        try:
            with path.open(encoding="utf-8") as stream:
                validate_mapping_data(yaml.safe_load(stream))
        except (OSError, yaml.YAMLError, ValueError) as exc:
            failures += 1
            print(f"{path}: {exc}")

    if not failures:
        print(f"validated {len(paths)} mapping file(s)")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
