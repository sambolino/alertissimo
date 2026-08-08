#!/usr/bin/env python3
"""
Collect ALeRCE payload samples for mapping inspection.

New clean script, independent of earlier collector versions.

Examples:
  python3 data/collect_alerce_payloads_retry.py
  python3 data/collect_alerce_payloads_retry.py --max-candidates 50
  python3 data/collect_alerce_payloads_retry.py --ztf-id ZTF21aaeyldq --max-candidates 50
  python3 data/collect_alerce_payloads_retry.py --include-heavy
"""

from __future__ import annotations

import argparse
import json
import tarfile
import traceback
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

DEFAULT_OUT_DIR = Path("data/alerce")
DEFAULT_SURVEYS = ["ztf", "lsst"]

# Current ALeRCE client/backend status observed during payload probing:
# these Python client methods exist, but LSST multisurvey implementations may
# raise NotImplementedError. Skip by default unless --try-unsupported is passed.
KNOWN_UNSUPPORTED = {
    ("lsst", "query_magstats"),
    ("lsst", "query_features"),
    ("lsst", "query_classifiers"),
}

GLOBAL_METHODS = [
    "query_classifiers",
]

OBJECT_METHODS = [
    "query_object",
    "query_detections",
    "query_non_detections",
    "query_forced_photometry",
    "query_lightcurve",
    "query_magstats",
    "query_probabilities",
    "query_features",
]

HEAVY_OBJECT_METHODS = [
    "get_stamps",
    "get_avro",
]

OID_KEYS = [
    "oid",
    "objectId",
    "object_id",
    "diaObjectId",
    "dia_object_id",
    "aid",
    "id",
]


@dataclass
class MethodResult:
    survey: str
    method: str
    status: str
    oid: str | None
    response_file: str | None
    attempts_file: str | None
    note: str | None = None
    error: str | None = None
    attributes: list[str] | None = None


def json_default(obj: Any) -> Any:
    """Serialize pandas/numpy/astropy/bytes-ish objects conservatively."""
    if obj is None:
        return None

    # pandas DataFrame/Series
    if hasattr(obj, "to_dict"):
        try:
            return obj.to_dict(orient="records")
        except TypeError:
            try:
                return obj.to_dict()
            except Exception:
                pass
        except Exception:
            pass

    # astropy table
    if hasattr(obj, "colnames"):
        try:
            return {name: json_default(obj[name]) for name in obj.colnames}
        except Exception:
            pass

    # numpy arrays/scalars
    if hasattr(obj, "tolist"):
        try:
            return obj.tolist()
        except Exception:
            pass

    if isinstance(obj, (bytes, bytearray)):
        return {
            "__type__": "bytes",
            "length": len(obj),
            "preview_hex": bytes(obj[:32]).hex(),
        }

    if isinstance(obj, (set, tuple)):
        return list(obj)

    return str(obj)


def to_jsonable(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=json_default))


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(data), indent=2, ensure_ascii=False), encoding="utf-8")


def is_empty_payload(obj: Any) -> bool:
    obj = to_jsonable(obj)
    if obj is None:
        return True
    if isinstance(obj, list):
        return len(obj) == 0
    if isinstance(obj, dict):
        if not obj:
            return True
        if "error" in obj and len(obj) <= 3:
            return True
        # ALeRCE lightcurve-like shape.
        lc_keys = {"detections", "non_detections", "forced_photometry"}
        if set(obj.keys()).issubset(lc_keys):
            return all(is_empty_payload(v) for v in obj.values())
        return False
    if isinstance(obj, str):
        return obj.strip() == ""
    return False


def extract_attributes(obj: Any, prefix: str = "") -> set[str]:
    """Extract flattened attribute paths from JSON-like objects."""
    obj = to_jsonable(obj)
    attrs: set[str] = set()

    if isinstance(obj, dict):
        for key, value in obj.items():
            key = str(key)
            path = f"{prefix}.{key}" if prefix else key
            attrs.add(path)
            attrs |= extract_attributes(value, path)
    elif isinstance(obj, list):
        # Avoid huge traversal; enough for schema inspection.
        for item in obj[:20]:
            attrs |= extract_attributes(item, prefix)
    return attrs


def find_oid_candidates(obj: Any) -> list[str]:
    obj = to_jsonable(obj)
    found: list[str] = []

    def visit(x: Any) -> None:
        if isinstance(x, dict):
            for k in OID_KEYS:
                val = x.get(k)
                if val not in (None, ""):
                    sval = str(val)
                    if sval not in found:
                        found.append(sval)
            for v in x.values():
                visit(v)
        elif isinstance(x, list):
            for item in x:
                visit(item)

    visit(obj)
    return found


def call_method(client: Any, method: str, survey: str, oid: str | None = None) -> Any:
    fn = getattr(client, method)

    if method == "query_object":
        return fn(oid, format="json", survey=survey)

    if method in {
        "query_detections",
        "query_non_detections",
        "query_forced_photometry",
        "query_lightcurve",
        "query_magstats",
        "query_probabilities",
        "query_features",
    }:
        return fn(oid, format="json", survey=survey)

    if method == "query_classifiers":
        return fn(format="json", survey=survey)

    if method == "get_stamps":
        return fn(oid=oid, format="numpy", survey=survey)

    if method == "get_avro":
        return fn(oid=oid, survey=survey)

    raise ValueError(f"No dispatch rule for method: {method}")


def discover_candidates(client: Any, survey: str, max_candidates: int, out_dir: Path) -> list[str]:
    """Best-effort candidate discovery via query_objects."""
    survey_dir = out_dir / survey
    attempts: list[dict[str, Any]] = []

    variants = [
        {"format": "json", "survey": survey, "page_size": max_candidates},
        {"format": "json", "survey": survey, "page_size": max_candidates, "count": False},
        {"format": "json", "survey": survey},
    ]

    for params in variants:
        try:
            response = client.query_objects(**params)
            response_json = to_jsonable(response)
            oids = find_oid_candidates(response_json)[:max_candidates]
            attempts.append({
                "params": params,
                "status": "ok",
                "n_oids": len(oids),
                "oids": oids,
            })
            save_json(survey_dir / "response_query_objects_discovery.json", response_json)
            save_json(survey_dir / "response_query_objects_discovery_attempts.json", attempts)
            if oids:
                return oids
        except Exception as exc:
            attempts.append({
                "params": params,
                "status": "error",
                "error": repr(exc),
                "traceback": traceback.format_exc(),
            })

    save_json(survey_dir / "response_query_objects_discovery_attempts.json", attempts)
    return []


def collect_method(
    client: Any,
    survey: str,
    method: str,
    candidates: list[str],
    out_dir: Path,
    retry_empty: bool,
    try_unsupported: bool,
) -> MethodResult:
    survey_dir = out_dir / survey
    survey_dir.mkdir(parents=True, exist_ok=True)
    attempts_file = survey_dir / f"response_{method}_attempts.json"

    if (survey, method) in KNOWN_UNSUPPORTED and not try_unsupported:
        result = MethodResult(
            survey=survey,
            method=method,
            status="known_unsupported",
            oid=None,
            response_file=None,
            attempts_file=str(attempts_file),
            note="Skipped by default; pass --try-unsupported to probe.",
            attributes=[],
        )
        save_json(attempts_file, [asdict(result)])
        return result

    object_dependent = method in OBJECT_METHODS or method in HEAVY_OBJECT_METHODS
    oids_to_try = candidates if object_dependent else [None]
    if object_dependent and not retry_empty:
        oids_to_try = candidates[:1]

    attempts: list[dict[str, Any]] = []
    selected_payload: Any = None
    selected_oid: str | None = None
    selected_status = "empty"
    selected_error: str | None = None

    if object_dependent and not oids_to_try:
        selected_status = "no_candidate_oid"
        attempts.append({"status": selected_status, "note": "No object IDs available."})

    for i, oid in enumerate(oids_to_try, start=1):
        try:
            response = call_method(client, method, survey, oid=oid)
            response_json = to_jsonable(response)
            attempt_path = survey_dir / f"response_{method}_attempt_{i:02d}.json"
            save_json(attempt_path, response_json)

            empty = is_empty_payload(response_json)
            attempts.append({
                "attempt": i,
                "oid": oid,
                "status": "ok_empty" if empty else "ok_non_empty",
                "file": str(attempt_path),
                "attribute_count": len(extract_attributes(response_json)),
            })

            if not empty:
                selected_payload = response_json
                selected_oid = oid
                selected_status = "ok"
                break

            # Keep first empty response as fallback selected payload.
            if selected_payload is None:
                selected_payload = response_json
                selected_oid = oid
                selected_status = "empty"

            if not retry_empty:
                break

        except Exception as exc:
            selected_error = repr(exc)
            attempts.append({
                "attempt": i,
                "oid": oid,
                "status": "error",
                "error": repr(exc),
                "traceback": traceback.format_exc(),
            })
            if isinstance(exc, NotImplementedError):
                selected_status = "not_implemented"
                break

    save_json(attempts_file, attempts)

    response_file: str | None = None
    attributes: list[str] = []
    if selected_payload is not None:
        response_path = survey_dir / f"response_{method}.json"
        save_json(response_path, selected_payload)
        response_file = str(response_path)
        attributes = sorted(extract_attributes(selected_payload))

    return MethodResult(
        survey=survey,
        method=method,
        status=selected_status,
        oid=selected_oid,
        response_file=response_file,
        attempts_file=str(attempts_file),
        error=selected_error,
        attributes=attributes,
    )


def write_attribute_tables(results: list[MethodResult], out_dir: Path) -> None:
    rows = []
    for result in results:
        for attr in result.attributes or []:
            rows.append({
                "survey": result.survey,
                "method": result.method,
                "status": result.status,
                "oid": result.oid or "",
                "attribute": attr,
            })

    lines = ["survey\tmethod\tstatus\toid\tattribute"]
    for row in rows:
        lines.append("\t".join(row[k].replace("\t", " ") for k in ["survey", "method", "status", "oid", "attribute"]))
    (out_dir / "attributes_all_surveys.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    unique = sorted({row["attribute"] for row in rows})
    (out_dir / "attributes_unique.txt").write_text("\n".join(unique) + "\n", encoding="utf-8")


def make_bundle(out_dir: Path) -> Path:
    bundle = out_dir / "alerce_payload_bundle_retry.tar.gz"
    with tarfile.open(bundle, "w:gz") as tar:
        for path in sorted(out_dir.rglob("*")):
            if path == bundle or path.is_dir():
                continue
            tar.add(path, arcname=str(path))
    return bundle


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect ALeRCE payload samples for mapping inspection.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory. Default: data/alerce")
    parser.add_argument("--surveys", nargs="+", choices=DEFAULT_SURVEYS, default=DEFAULT_SURVEYS)
    parser.add_argument("--ztf-id", default=None, help="Preferred ZTF object ID.")
    parser.add_argument("--lsst-id", default=None, help="Preferred LSST object ID.")
    parser.add_argument("--max-candidates", type=int, default=25, help="Maximum discovered candidate OIDs per survey. Default: 25")
    parser.add_argument("--no-retry-empty", action="store_true", help="Do not retry methods that return empty payloads.")
    parser.add_argument("--try-unsupported", action="store_true", help="Probe known unsupported LSST multisurvey methods anyway.")
    parser.add_argument("--include-heavy", action="store_true", help="Include get_stamps and get_avro. Can be large or fail.")
    parser.add_argument("--include-catshtm", action="store_true", help="Reserved; currently recorded but not used.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from alerce.core import Alerce
    except Exception as exc:
        raise SystemExit(
            "Could not import ALeRCE client. Install it with:\n"
            "  pip install alerce\n"
            f"Original error: {exc!r}"
        )

    client = Alerce()
    retry_empty = not args.no_retry_empty
    preferred_ids = {"ztf": args.ztf_id, "lsst": args.lsst_id}
    methods = list(GLOBAL_METHODS) + list(OBJECT_METHODS)
    if args.include_heavy:
        methods += HEAVY_OBJECT_METHODS

    all_results: list[MethodResult] = []
    summary: dict[str, Any] = {
        "script": "collect_alerce_payloads_retry.py",
        "surveys": args.surveys,
        "max_candidates": args.max_candidates,
        "retry_empty": retry_empty,
        "try_unsupported": args.try_unsupported,
        "include_heavy": args.include_heavy,
        "include_catshtm": args.include_catshtm,
        "known_unsupported": sorted(f"{s}/{m}" for s, m in KNOWN_UNSUPPORTED),
        "surveys_detail": {},
    }

    for survey in args.surveys:
        print(f"\n=== {survey} ===")
        survey_dir = out_dir / survey
        survey_dir.mkdir(parents=True, exist_ok=True)

        candidates: list[str] = []
        if preferred_ids.get(survey):
            candidates.append(str(preferred_ids[survey]))

        discovered = discover_candidates(client, survey, args.max_candidates, out_dir)
        for oid in discovered:
            if oid not in candidates:
                candidates.append(oid)
        candidates = candidates[: args.max_candidates]
        save_json(survey_dir / "candidate_oids.json", candidates)

        print(f"candidate OIDs: {len(candidates)}")
        if candidates:
            print(f"first candidate: {candidates[0]}")

        summary["surveys_detail"][survey] = {
            "candidate_count": len(candidates),
            "candidates": candidates,
            "methods": {},
        }

        for method in methods:
            print(f"  {method} ...", end="", flush=True)
            result = collect_method(
                client=client,
                survey=survey,
                method=method,
                candidates=candidates,
                out_dir=out_dir,
                retry_empty=retry_empty,
                try_unsupported=args.try_unsupported,
            )
            all_results.append(result)
            summary["surveys_detail"][survey]["methods"][method] = asdict(result)
            tail = f" oid={result.oid}" if result.oid else ""
            print(f" {result.status}{tail}")

    save_json(out_dir / "payload_summary.json", summary)
    save_json(out_dir / "method_results.json", [asdict(r) for r in all_results])
    write_attribute_tables(all_results, out_dir)
    bundle = make_bundle(out_dir)

    print("\nWrote:")
    print(f"  {out_dir / 'payload_summary.json'}")
    print(f"  {out_dir / 'method_results.json'}")
    print(f"  {out_dir / 'attributes_all_surveys.tsv'}")
    print(f"  {out_dir / 'attributes_unique.txt'}")
    print(f"  {bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
