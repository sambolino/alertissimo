#!/usr/bin/env python3
"""Fetch Fink LSST API schema responses and audit mapped attributes.

Run from the Alertissimo repository root:

    python3 data/fetch_fink_lsst_schemas.py \
      --mapping alertissimo/core/brokers/registry/fink/lsst/mappings.yaml

The script writes raw responses and a small attribute audit to data/fink/lsst/.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "https://api.lsst.fink-portal.org/api/v1"

METHODS = [
    "sources",
    "objects",
    "fp",
    "conesearch",
    "cutouts",
    "schema",
    "sso",
    "resolver",
    "skymap",
    "statistics",
    "tags",
]

METADATA_METHODS = {"schema", "tags"}

ATTR_RE = re.compile(r"(?<![A-Za-z0-9_/.-])([A-Za-z][A-Za-z0-9_]*:[A-Za-z0-9_.$*()\-/]+)")
FIELD_LINE_RE = re.compile(r"^\s*field:\s*['\"]?([^'\"#\n]+)['\"]?")
TOP_MAPPING_KEY_RE = re.compile(r"^\s{2}([^\s:#][^:#]*):\s*(?:#.*)?$")


def request_json(method: str) -> dict[str, Any]:
    """Return one raw API response wrapper for a method."""
    if method in METADATA_METHODS:
        url = f"{BASE_URL}/{method}"
        req = Request(url, method="GET", headers={"Accept": "application/json"})
    else:
        url = f"{BASE_URL}/schema"
        payload = json.dumps({"endpoint": f"/api/v1/{method}"}).encode("utf-8")
        req = Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    try:
        with urlopen(req, timeout=40) as response:
            raw = response.read()
            text = raw.decode("utf-8", errors="replace")
            try:
                body: Any = json.loads(text)
            except json.JSONDecodeError:
                body = {"_raw_text": text}
            return {
                "method": method,
                "url": url,
                "ok": True,
                "status": getattr(response, "status", None),
                "body": body,
            }
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(text)
        except json.JSONDecodeError:
            body = {"_raw_text": text}
        return {
            "method": method,
            "url": url,
            "ok": False,
            "status": exc.code,
            "error": str(exc),
            "body": body,
        }
    except URLError as exc:
        return {
            "method": method,
            "url": url,
            "ok": False,
            "status": None,
            "error": str(exc),
            "body": None,
        }


def looks_like_real_attribute(value: str) -> bool:
    value = value.strip().strip("'\"")
    if "://" in value:
        return False
    if value.startswith(("/api/", "api/")):
        return False
    if value.count(":") != 1:
        return False
    prefix, name = value.split(":", 1)
    if prefix.lower() in {"http", "https"}:
        return False
    if not prefix or not name:
        return False
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9_]*$", prefix))


def extract_attributes(obj: Any) -> set[str]:
    """Extract Fink-style attributes from arbitrary schema JSON."""
    found: set[str] = set()

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            for key, value in x.items():
                if isinstance(key, str) and looks_like_real_attribute(key):
                    found.add(key)
                if key in {"name", "field", "column", "attribute"} and isinstance(value, str):
                    for match in ATTR_RE.findall(value):
                        if looks_like_real_attribute(match):
                            found.add(match)
                walk(value)
        elif isinstance(x, list):
            for item in x:
                walk(item)
        elif isinstance(x, str):
            for match in ATTR_RE.findall(x):
                if looks_like_real_attribute(match):
                    found.add(match)

    walk(obj)
    return found


def parse_mapping_fields(mapping_path: Path) -> dict[str, list[str]]:
    """Parse mapping source fields to semantic paths without loading YAML."""
    mapped: dict[str, list[str]] = defaultdict(list)
    if not mapping_path.exists():
        return {}

    current_path: str | None = None
    for line in mapping_path.read_text(encoding="utf-8").splitlines():
        key_match = TOP_MAPPING_KEY_RE.match(line)
        if key_match:
            current_path = key_match.group(1).strip()
            continue

        field_match = FIELD_LINE_RE.match(line)
        if field_match and current_path:
            field = field_match.group(1).strip()
            if looks_like_real_attribute(field):
                mapped[field].append(current_path)

    return {field: sorted(set(paths)) for field, paths in mapped.items()}


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Fink LSST schemas and audit real attributes.")
    parser.add_argument(
        "--mapping",
        default="alertissimo/core/brokers/registry/fink/lsst/mappings.yaml",
        help="Mapping file to compare against real attributes.",
    )
    parser.add_argument(
        "--outdir",
        default="data/fink/lsst",
        help="Output directory. Default: data/fink/lsst",
    )
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    method_attributes: dict[str, list[str]] = {}
    for method in METHODS:
        response = request_json(method)
        write_json(outdir / f"response_{method}.json", response)
        if method not in METADATA_METHODS and response.get("ok"):
            attrs = sorted(extract_attributes(response.get("body")))
            method_attributes[method] = attrs

    all_attributes = sorted({attr for attrs in method_attributes.values() for attr in attrs})
    mapped = parse_mapping_fields(Path(args.mapping))

    (outdir / "real_attributes.txt").write_text("\n".join(all_attributes) + "\n", encoding="utf-8")

    with (outdir / "real_attributes.tsv").open("w", encoding="utf-8") as fh:
        fh.write("attribute\tmethods\tmapped\tcatalog_paths\n")
        for attr in all_attributes:
            methods = [method for method, attrs in method_attributes.items() if attr in attrs]
            paths = mapped.get(attr, [])
            fh.write(
                f"{attr}\t{','.join(methods)}\t{str(bool(paths)).lower()}\t{';'.join(paths)}\n"
            )

    write_json(outdir / "real_attributes_by_method.json", method_attributes)
    (outdir / "metadata_methods.txt").write_text("\n".join(sorted(METADATA_METHODS)) + "\n", encoding="utf-8")

    mapped_fields = set(mapped)
    real_fields = set(all_attributes)
    unmapped = sorted(real_fields - mapped_fields)
    mapped_not_seen = sorted(mapped_fields - real_fields)

    audit = [
        "# Fink LSST mapping audit",
        "",
        f"Mapping file: `{args.mapping}`",
        "",
        f"Real attributes found: {len(real_fields)}",
        f"Mapped source attributes: {len(mapped_fields)}",
        f"Unmapped real attributes: {len(unmapped)}",
        f"Mapped source attributes not seen: {len(mapped_not_seen)}",
        "",
        "## Unmapped real attributes",
        "",
    ]
    audit.extend(f"- `{x}`" for x in unmapped)
    audit.extend(["", "## Mapped source attributes not seen", ""])
    audit.extend(f"- `{x}` → {', '.join(mapped[x])}" for x in mapped_not_seen)
    audit.append("")
    (outdir / "mapping_audit.md").write_text("\n".join(audit), encoding="utf-8")

    print(f"Wrote raw responses and attribute audit to {outdir}")
    print(f"Methods: {', '.join(METHODS)}")
    print(f"Real attributes: {len(real_fields)}")
    print(f"Unmapped real attributes: {len(unmapped)}")
    print(f"Mapped source attributes not seen: {len(mapped_not_seen)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
