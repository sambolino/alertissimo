#!/usr/bin/env python3
"""Inspect the structural shape of a saved JSON broker payload."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def inspect_payload_shape(value: Any, path: str = "$", *, max_list_items: int = 3) -> list[str]:
    """Return a compact, deterministic description of a JSON-compatible value."""
    if isinstance(value, dict):
        lines = [f"{path}: object ({len(value)} keys)"]
        for key in sorted(value):
            lines.extend(inspect_payload_shape(value[key], f"{path}.{key}", max_list_items=max_list_items))
        return lines
    if isinstance(value, list):
        lines = [f"{path}: array ({len(value)} items)"]
        for index, item in enumerate(value[:max_list_items]):
            lines.extend(inspect_payload_shape(item, f"{path}[{index}]", max_list_items=max_list_items))
        if len(value) > max_list_items:
            lines.append(f"{path}[...]: {len(value) - max_list_items} more items")
        return lines
    kind = "null" if value is None else type(value).__name__
    return [f"{path}: {kind}"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.payload.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print("\n".join(inspect_payload_shape(payload)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
