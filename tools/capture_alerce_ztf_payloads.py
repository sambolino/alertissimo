#!/usr/bin/env python3
"""Capture raw JSON responses from the official ALeRCE client for offline tests."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

KNOWN_OBJECTS = (
    "ZTF21aaeyldq", "ZTF17aaaaaak", "ZTF17aaaaaal", "ZTF18abbuksn",
)
OBJECT_ENDPOINTS = (
    "query_object", "query_detections", "query_non_detections",
    "query_forced_photometry", "query_lightcurve", "query_probabilities",
    "query_magstats", "query_features",
)


def _json_value(value: Any) -> Any:
    """Make client containers serializable without changing response semantics."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if hasattr(value, "to_dict"):
        try:
            return _json_value(value.to_dict(orient="records"))
        except TypeError:
            return _json_value(value.to_dict())
    if hasattr(value, "tolist"):
        return _json_value(value.tolist())
    raise TypeError(f"official client returned unsupported JSON value {type(value)!r}")


def _nonempty(value: Any) -> bool:
    return bool(value) if isinstance(value, (dict, list, tuple)) else value is not None


def capture(output_dir: Path) -> int:
    from alerce.core import Alerce

    output_dir.mkdir(parents=True, exist_ok=True)
    client = Alerce()
    manifest: dict[str, Any] = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "client": "alerce.core.Alerce",
        "survey": "ztf",
        "format": "json",
        "calls": {},
    }
    discovery = None
    try:
        discovery = client.query_objects(
            survey="ztf", format="json", page=1, page_size=100,
        )
        serial = _json_value(discovery)
        if _nonempty(serial):
            (output_dir / "query_objects.json").write_text(
                json.dumps(serial, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            manifest["calls"]["query_objects"] = {"status": "ok", "query": "page=1,page_size=100"}
    except Exception as exc:  # continue capturing independent endpoints
        manifest["calls"]["query_objects"] = {"status": "failed", "error": repr(exc)}

    discovered_ids: list[str] = []
    rows = discovery if isinstance(discovery, list) else []
    for row in rows:
        if isinstance(row, dict) and row.get("oid"):
            discovered_ids.append(str(row["oid"]))
    candidates = tuple(dict.fromkeys((*KNOWN_OBJECTS, *discovered_ids)))

    failures = 0
    for endpoint in OBJECT_ENDPOINTS:
        result = None
        errors = []
        chosen = None
        for oid in candidates:
            try:
                # Explicit survey/format is intentional for every multisurvey call.
                candidate = getattr(client, endpoint)(oid=oid, survey="ztf", format="json")
                serial = _json_value(candidate)
                if _nonempty(serial):
                    result, chosen = serial, oid
                    break
                errors.append(f"{oid}: empty response")
            except Exception as exc:
                errors.append(f"{oid}: {exc!r}")
        if result is None:
            failures += 1
            manifest["calls"][endpoint] = {"status": "failed", "attempts": errors}
            continue
        (output_dir / f"{endpoint}.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        manifest["calls"][endpoint] = {"status": "ok", "object": chosen}

    (output_dir / "capture_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for endpoint, result in manifest["calls"].items():
        print(f"{endpoint}: {result['status']}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    return capture(parser.parse_args().output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
