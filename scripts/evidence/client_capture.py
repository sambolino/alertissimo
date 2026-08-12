"""Small, capture-only helpers shared by the Python client entrypoints."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import subprocess
from datetime import date, datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any


def prepare_output(path: str | None, label: str) -> tuple[Path, str]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(path or f"/tmp/{label}-capture-{stamp}").expanduser()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"ERROR: destination exists and is non-empty: {out}")
    out.mkdir(parents=True, exist_ok=True)
    return out.resolve(), datetime.now(timezone.utc).isoformat()


def package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unavailable"


def git_value(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], check=True, capture_output=True, text=True
        ).stdout.strip() or "unavailable"
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def jsonable(value: Any) -> Any:
    """Represent client-visible values in JSON without changing provider field names."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if dataclasses.is_dataclass(value):
        return jsonable(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    if hasattr(value, "to_dict"):
        try:
            return jsonable(value.to_dict(orient="records"))
        except TypeError:
            return jsonable(value.to_dict())
    if hasattr(value, "item"):
        return jsonable(value.item())
    if hasattr(value, "__dict__"):
        return {
            k: jsonable(v)
            for k, v in vars(value).items()
            if not k.startswith("_") and not callable(v)
        }
    raise TypeError(f"cannot serialize client value {type(value).__name__}")


def write_json(path: Path, value: Any) -> Any:
    clean = jsonable(value)
    path.write_text(json.dumps(clean, indent=2, sort_keys=True) + "\n")
    return clean


def describe(value: Any) -> dict[str, Any]:
    kind = type(value).__name__
    rows = len(value) if isinstance(value, list) else 1
    keys: set[str] = set()
    if isinstance(value, list):
        for row in value:
            if isinstance(row, dict):
                keys.update(row)
    elif isinstance(value, dict):
        keys.update(value)
    return {"json_type": kind, "rows": rows, "union_field_count": len(keys)}


def finish(out: Path, script: Path, payloads: list[str], inventory: dict[str, Any]) -> None:
    write_json(out / "inventory.txt", inventory)
    with (out / "SHA256SUMS.txt").open("w") as sums:
        for name in payloads:
            digest = hashlib.sha256((out / name).read_bytes()).hexdigest()
            sums.write(f"{digest}  {name}\n")
    (out / "capture_script.sha256").write_text(
        f"{hashlib.sha256(script.read_bytes()).hexdigest()}  {script.name}\n"
    )
    print("Verify response hashes with:")
    print(f'  (cd "{out}" && sha256sum -c SHA256SUMS.txt)')
