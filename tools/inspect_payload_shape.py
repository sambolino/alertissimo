#!/usr/bin/env python3
"""Print a small, deterministic structural summary of a saved JSON payload."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "list"
    return type(value).__name__


def _scalar_example(value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return rendered if len(rendered) <= 80 else rendered[:77] + "..."


def describe_payload(payload: Any, *, depth: int = 3, max_list_items: int = 3) -> list[str]:
    """Return stable lines describing containers and representative scalar values."""
    lines = [f"top-level type: {_type_name(payload)}"]
    if isinstance(payload, dict):
        lines.append("top-level keys: " + (", ".join(sorted(payload)) or "none"))

    def visit(value: Any, path: str, remaining: int) -> None:
        label = path or "."
        if isinstance(value, dict):
            keys = sorted(value)
            empty = sum(item in (None, "", [], {}) for item in value.values())
            nulls = sum(item is None for item in value.values())
            suffix = f"; empty={empty}; null={nulls}" if empty or nulls else ""
            lines.append(f"{label}: object[{len(keys)}] keys={', '.join(keys) or 'none'}{suffix}")
            if remaining:
                for key in keys:
                    visit(value[key], key if not path else f"{path}.{key}", remaining - 1)
        elif isinstance(value, list):
            lines.append(f"{label}: list[{len(value)}]")
            samples = value[:max_list_items]
            object_keys = sorted({key for item in samples if isinstance(item, dict) for key in item})
            if object_keys:
                lines.append(f"{label}[] object key sample: {', '.join(object_keys)}")
            if remaining:
                for index, item in enumerate(samples):
                    visit(item, f"{label}[{index}]", remaining - 1)
        else:
            lines.append(f"{label}: {_type_name(value)} example={_scalar_example(value)}")

    visit(payload, "", depth)
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path)
    parser.add_argument("--depth", type=int, default=3)
    parser.add_argument("--max-list-items", type=int, default=3)
    args = parser.parse_args()
    if args.depth < 0 or args.max_list_items < 0:
        parser.error("--depth and --max-list-items must be non-negative")
    try:
        payload = json.loads(args.payload.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        parser.error(f"cannot read JSON payload: {error}")
    print("\n".join(describe_payload(payload, depth=args.depth, max_list_items=args.max_list_items)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
