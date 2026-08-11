#!/usr/bin/env python3
"""Capture raw JSON responses from the official ALeRCE client for offline tests."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
import inspect
import json
from pathlib import Path
from typing import Any

KNOWN_OBJECTS = (
    "ZTF21aaeyldq",
    "ZTF17aaaaaak",
    "ZTF17aaaaaal",
    "ZTF18abbuksn",
)
OBJECT_ENDPOINTS = (
    "query_object",
    "query_detections",
    "query_non_detections",
    "query_forced_photometry",
    "query_lightcurve",
    "query_probabilities",
    "query_magstats",
    "query_features",
)


def _package_version() -> str:
    try:
        return version("alerce")
    except PackageNotFoundError:
        return "unknown"


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


def _result_entry(
    value: Any = None, *, query: str | None = None, error: BaseException | None = None
) -> dict[str, Any]:
    """Describe an attempted call, keeping valid empty results distinct from errors."""
    entry: dict[str, Any] = {
        "status": "failed" if error else ("ok" if _nonempty(value) else "empty")
    }
    if query is not None:
        entry["query"] = query
    if error is not None:
        entry["error"] = repr(error)
    return entry


def _invocation(method: Any, endpoint: str, oid: str | None = None) -> dict[str, Any]:
    """Build endpoint-specific arguments verified against the installed client."""
    requested: dict[str, Any]
    if endpoint == "query_objects":
        requested = {"survey": "ztf", "format": "json", "page": 1, "page_size": 100}
    elif endpoint in OBJECT_ENDPOINTS:
        requested = {"oid": oid, "format": "json"}
    else:  # pragma: no cover - internal programming error
        raise ValueError(f"unknown endpoint {endpoint!r}")

    signature = inspect.signature(method)
    # Object methods differ across official-client releases. Survey is explicit
    # only when that installed method actually declares it.
    if endpoint != "query_objects" and "survey" in signature.parameters:
        requested["survey"] = "ztf"
    accepts_extra = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    unsupported = set(requested) - set(signature.parameters)
    if unsupported and not accepts_extra:
        raise TypeError(
            f"{endpoint}{signature} does not support configured arguments "
            f"{sorted(unsupported)}"
        )
    # Binding catches client drift before an API request and before trying another OID.
    signature.bind(**requested)
    return requested


def capture(output_dir: Path) -> int:
    from alerce.core import Alerce

    output_dir.mkdir(parents=True, exist_ok=True)
    client = Alerce()
    manifest: dict[str, Any] = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "client_package": "alerce",
        "client_version": _package_version(),
        "client": "alerce.core.Alerce",
        "survey": "ztf",
        "requested_format": "json",
        "calls": {},
    }
    discovery = None
    try:
        discovery = client.query_objects(
            **_invocation(client.query_objects, "query_objects")
        )
        serial = _json_value(discovery)
        manifest["calls"]["query_objects"] = _result_entry(
            serial, query="page=1,page_size=100"
        )
        if _nonempty(serial):
            (output_dir / "query_objects.json").write_text(
                json.dumps(serial, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
    except Exception as exc:  # continue capturing independent endpoints
        manifest["calls"]["query_objects"] = _result_entry(
            query="page=1,page_size=100", error=exc
        )

    discovered_ids: list[str] = []
    rows = serial if "serial" in locals() and isinstance(serial, list) else []
    for row in rows:
        if isinstance(row, dict) and row.get("oid"):
            discovered_ids.append(str(row["oid"]))
    candidates = tuple(dict.fromkeys((*KNOWN_OBJECTS, *discovered_ids)))

    failures = int(manifest["calls"]["query_objects"]["status"] == "failed")
    for endpoint in OBJECT_ENDPOINTS:
        result = None
        errors = []
        chosen = None
        had_empty_response = False
        for oid in candidates:
            try:
                method = getattr(client, endpoint)
                candidate = method(**_invocation(method, endpoint, oid))
                serial = _json_value(candidate)
                if _nonempty(serial):
                    result, chosen = serial, oid
                    break
                had_empty_response = True
                errors.append(f"{oid}: empty response")
            except TypeError as exc:
                # A signature mismatch is a capture-tool bug, not evidence that an OID is bad.
                errors.append(f"invocation error: {exc!r}")
                break
            except Exception as exc:
                errors.append(f"{oid}: {exc!r}")
        if result is None:
            status = (
                "empty"
                if had_empty_response
                and all("empty response" in attempt for attempt in errors)
                else "failed"
            )
            failures += status == "failed"
            manifest["calls"][endpoint] = {"status": status, "attempts": errors}
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
