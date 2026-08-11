#!/usr/bin/env python3
"""Capture complete ALeRCE/ZTF JSON responses with the official Python client."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
import inspect
import json
from pathlib import Path
from typing import Any, Iterator

KNOWN_OBJECTS = (
    "ZTF18abbuksn",
    "ZTF21aaeyldq",
    "ZTF17aaaaaak",
    "ZTF17aaaaaal",
)
SELECTED_OID = "ZTF18abbuksn"
HTTP_TIMEOUT_SECONDS = 20
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


def _shape(value: Any) -> str:
    if isinstance(value, list):
        return f"list[{len(value)}]"
    if isinstance(value, dict):
        return f"dict keys={sorted(value)}"
    return type(value).__name__


def _result_entry(
    value: Any = None, *, query: Any = None, error: BaseException | None = None
) -> dict[str, Any]:
    """Describe a call while keeping empty results distinct from failures."""
    entry: dict[str, Any] = {
        "status": "failed" if error else ("ok" if _nonempty(value) else "empty")
    }
    if query is not None:
        entry["query"] = query
    if error is not None:
        entry["error"] = repr(error)
    else:
        entry["shape"] = _shape(value)
    return entry


def _invocation(method: Any, endpoint: str, oid: str | None = None) -> dict[str, Any]:
    """Validate endpoint arguments separately from executing client code."""
    if endpoint == "query_objects":
        requested: dict[str, Any] = {
            "oid": list(KNOWN_OBJECTS), "survey": "ztf", "format": "json"
        }
    elif endpoint in OBJECT_ENDPOINTS:
        requested = {"oid": oid, "format": "json"}
    else:  # pragma: no cover - internal programming error
        raise ValueError(f"unknown endpoint {endpoint!r}")

    signature = inspect.signature(method)
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
    signature.bind(**requested)
    return requested


@contextmanager
def _finite_http_timeout(
    seconds: int = HTTP_TIMEOUT_SECONDS, requests_module: Any = None
) -> Iterator[None]:
    """Give requests made inside the legacy ZTF client a finite default timeout."""
    requests_module = requests_module or import_module("requests")
    original = requests_module.sessions.Session.request

    def request(session: Any, method: str, url: str, **kwargs: Any) -> Any:
        kwargs.setdefault("timeout", seconds)
        return original(session, method, url, **kwargs)

    requests_module.sessions.Session.request = request
    try:
        yield
    finally:
        requests_module.sessions.Session.request = original


def _write_fixture(output_dir: Path, endpoint: str, value: Any) -> None:
    (output_dir / f"{endpoint}.json").write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


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
        "format": "json",
        "http_timeout_seconds": HTTP_TIMEOUT_SECONDS,
        "calls": {},
    }
    failures = 0
    calls = (("query_objects", list(KNOWN_OBJECTS)),) + tuple(
        (endpoint, SELECTED_OID) for endpoint in OBJECT_ENDPOINTS
    )

    with _finite_http_timeout():
        for endpoint, query in calls:
            print(f"{endpoint}: requesting {query}", flush=True)
            method = getattr(client, endpoint)
            # Signature drift is a configuration error. Validate before entering the
            # execution handler so a TypeError raised *inside* the client stays a call failure.
            try:
                arguments = _invocation(
                    method, endpoint, None if endpoint == "query_objects" else SELECTED_OID
                )
            except (TypeError, ValueError) as error:
                entry = _result_entry(query=query, error=error)
            else:
                try:
                    value = _json_value(method(**arguments))
                except Exception as error:  # continue capturing independent endpoints
                    entry = _result_entry(query=query, error=error)
                else:
                    entry = _result_entry(value, query=query)
                    if endpoint == "query_objects" and isinstance(value, dict):
                        entry["item_count"] = len(value.get("items", []))
                    if entry["status"] == "ok":
                        _write_fixture(output_dir, endpoint, value)
            manifest["calls"][endpoint] = entry
            failures += entry["status"] == "failed"
            print(f"{endpoint}: {entry['status']} ({entry.get('shape', 'no response')})", flush=True)

    (output_dir / "capture_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    return capture(parser.parse_args().output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
