#!/usr/bin/env python3
"""
Collect representative ALeRCE payloads for mapping inspection.

Run from the Alertissimo repository root, e.g.:

    python3 data/collect_alerce_payloads.py --ztf-id ZTF21aaeyldq --lsst-id 396895411240977

If IDs are omitted, the script tries to discover one object per survey using
Alerce.query_objects(..., survey=<survey>). Known IDs are still preferred.

Outputs:
    data/alerce/<survey>/response_<method>.json
    data/alerce/<survey>/attributes_<method>.txt
    data/alerce/<survey>/attributes_all.txt
    data/alerce/<survey>/attributes_all.tsv
    data/alerce/payload_summary.json
    data/alerce/alerce_payload_bundle.tar.gz

The goal is not scientific completeness. The goal is to capture real payload
shapes so mappings.yaml can be built from evidence instead of docs alone.
"""

from __future__ import annotations

import argparse
import base64
import dataclasses
import datetime as _dt
import json
import math
import os
import tarfile
import traceback
from pathlib import Path
from typing import Any, Callable, Iterable


DEFAULT_SURVEYS = ["ztf", "lsst"]
DEFAULT_OUT_DIR = Path("data/alerce")

# A few very small, broad discovery attempts. These are deliberately conservative.
# They are only fallback probes if the user does not pass --ztf-id / --lsst-id.
DISCOVERY_ATTEMPTS = [
    {"format": "json", "page": 1, "page_size": 3},
    {"format": "json", "page": 1, "page_size": 3, "count": False},
    # Coordinate example from ALeRCE docs; may or may not return data in a given survey.
    {"format": "json", "ra": 10.0, "dec": -20.0, "radius": 30, "page": 1, "page_size": 3},
]

OID_KEYS = [
    "oid",
    "objectId",
    "object_id",
    "diaObjectId",
    "r:diaObjectId",
    "aid",
    "id",
]

RA_KEYS = ["ra", "meanra", "r:ra", "decMeanRa", "r:diaObject_ra"]
DEC_KEYS = ["dec", "meandec", "r:dec", "decMeanDec", "r:diaObject_dec"]


@dataclasses.dataclass
class CallResult:
    method: str
    ok: bool
    path: str | None = None
    error: str | None = None
    traceback: str | None = None
    attributes: list[str] = dataclasses.field(default_factory=list)


def import_client():
    try:
        from alerce.core import Alerce  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on local env
        raise SystemExit(
            "Could not import ALeRCE client. Install it in this environment, e.g.\n"
            "    pip install alerce\n\n"
            f"Original import error: {exc}"
        )
    return Alerce()


def is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def jsonable(value: Any) -> Any:
    """Convert common scientific/python-client objects to JSON-serializable data."""
    if is_scalar(value):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return value

    if isinstance(value, bytes):
        return {
            "__bytes__": True,
            "encoding": "base64",
            "length": len(value),
            "data": base64.b64encode(value[:2048]).decode("ascii"),
            "truncated_to_bytes": min(len(value), 2048),
        }

    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]

    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}

    # pandas DataFrame / Series
    if hasattr(value, "to_dict"):
        try:
            import pandas as pd  # type: ignore
            if isinstance(value, pd.DataFrame):
                return jsonable(value.to_dict(orient="records"))
            if isinstance(value, pd.Series):
                return jsonable(value.to_dict())
        except Exception:
            pass

        try:
            return jsonable(value.to_dict())
        except Exception:
            pass

    # astropy Table
    if hasattr(value, "colnames") and hasattr(value, "as_array"):
        try:
            return [
                {name: jsonable(row[name]) for name in value.colnames}
                for row in value
            ]
        except Exception:
            pass

    # numpy scalar/array
    if hasattr(value, "tolist"):
        try:
            return jsonable(value.tolist())
        except Exception:
            pass

    return repr(value)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")


def extract_attributes(data: Any, prefix: str = "") -> set[str]:
    """Extract dotted leaf attributes from JSON-like payloads."""
    attrs: set[str] = set()

    if isinstance(data, dict):
        if not data:
            if prefix:
                attrs.add(prefix)
            return attrs
        for key, value in data.items():
            key = str(key)
            child = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                attrs.update(extract_attributes(value, child))
            elif isinstance(value, list):
                # If list contains dicts, capture their inner keys. Also record the list itself.
                attrs.add(child)
                for item in value[:25]:
                    if isinstance(item, dict):
                        attrs.update(extract_attributes(item, child))
            else:
                attrs.add(child)
    elif isinstance(data, list):
        for item in data[:100]:
            if isinstance(item, dict):
                attrs.update(extract_attributes(item, prefix))
            elif prefix:
                attrs.add(prefix)
    elif prefix:
        attrs.add(prefix)

    return attrs


def first_record(data: Any) -> dict[str, Any] | None:
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                return item
    if isinstance(data, dict):
        # Common wrapper shapes
        for key in ["data", "items", "results", "objects", "detections"]:
            val = data.get(key)
            rec = first_record(val)
            if rec:
                return rec
        return data
    return None


def find_first_key(data: Any, keys: Iterable[str]) -> Any | None:
    keys_l = list(keys)
    if isinstance(data, dict):
        for key in keys_l:
            if key in data and data[key] not in (None, ""):
                return data[key]
        for value in data.values():
            found = find_first_key(value, keys_l)
            if found not in (None, ""):
                return found
    elif isinstance(data, list):
        for item in data:
            found = find_first_key(item, keys_l)
            if found not in (None, ""):
                return found
    return None


def discover_oid(client: Any, survey: str, out_dir: Path) -> tuple[str | None, Any | None, list[dict[str, Any]]]:
    attempts_log: list[dict[str, Any]] = []

    for params in DISCOVERY_ATTEMPTS:
        call_params = dict(params)
        call_params["survey"] = survey
        try:
            payload = client.query_objects(**call_params)
            data = jsonable(payload)
            oid = find_first_key(data, OID_KEYS)
            attempts_log.append({"params": call_params, "ok": True, "oid": oid})
            if oid:
                write_json(out_dir / f"response_discovery_query_objects_{survey}.json", data)
                return str(oid), data, attempts_log
        except Exception as exc:
            attempts_log.append({"params": call_params, "ok": False, "error": str(exc)})

    return None, None, attempts_log


def safe_call(
    *,
    client: Any,
    survey: str,
    method_name: str,
    call: Callable[[], Any],
    out_dir: Path,
) -> CallResult:
    try:
        payload = call()
        data = jsonable(payload)
        path = out_dir / survey / f"response_{method_name}.json"
        write_json(path, data)
        attrs = sorted(extract_attributes(data))
        (out_dir / survey / f"attributes_{method_name}.txt").write_text("\n".join(attrs) + "\n", encoding="utf-8")
        return CallResult(method=method_name, ok=True, path=str(path), attributes=attrs)
    except Exception as exc:
        err = {
            "method": method_name,
            "survey": survey,
            "ok": False,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        path = out_dir / survey / f"error_{method_name}.json"
        write_json(path, err)
        return CallResult(
            method=method_name,
            ok=False,
            path=str(path),
            error=str(exc),
            traceback=err["traceback"],
        )


def collect_for_survey(
    *,
    client: Any,
    survey: str,
    oid: str | None,
    out_dir: Path,
    include_heavy: bool,
    include_catshtm: bool,
) -> dict[str, Any]:
    survey_dir = out_dir / survey
    survey_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "survey": survey,
        "input_oid": oid,
        "resolved_oid": None,
        "discovery_attempts": [],
        "calls": [],
        "all_attributes": [],
    }

    if not oid:
        oid, discovery_payload, attempts_log = discover_oid(client, survey, out_dir)
        summary["discovery_attempts"] = attempts_log
        if discovery_payload is not None:
            attrs = sorted(extract_attributes(discovery_payload))
            (survey_dir / "attributes_discovery_query_objects.txt").write_text("\n".join(attrs) + "\n", encoding="utf-8")

    summary["resolved_oid"] = oid

    if not oid:
        summary["status"] = "no_object_id_available"
        write_json(survey_dir / "summary.json", summary)
        return summary

    def add(result: CallResult):
        summary["calls"].append(dataclasses.asdict(result))

    # Core payloads for mapping.
    add(safe_call(
        client=client,
        survey=survey,
        method_name="query_object",
        out_dir=out_dir,
        call=lambda: client.query_object(oid, format="json", survey=survey),
    ))
    add(safe_call(
        client=client,
        survey=survey,
        method_name="query_detections",
        out_dir=out_dir,
        call=lambda: client.query_detections(oid, format="json", survey=survey),
    ))
    add(safe_call(
        client=client,
        survey=survey,
        method_name="query_non_detections",
        out_dir=out_dir,
        call=lambda: client.query_non_detections(oid, format="json", survey=survey),
    ))
    add(safe_call(
        client=client,
        survey=survey,
        method_name="query_forced_photometry",
        out_dir=out_dir,
        call=lambda: client.query_forced_photometry(oid, format="json", survey=survey),
    ))
    add(safe_call(
        client=client,
        survey=survey,
        method_name="query_lightcurve",
        out_dir=out_dir,
        call=lambda: client.query_lightcurve(oid, format="json", survey=survey),
    ))
    add(safe_call(
        client=client,
        survey=survey,
        method_name="query_magstats",
        out_dir=out_dir,
        call=lambda: client.query_magstats(oid, format="json", survey=survey),
    ))
    add(safe_call(
        client=client,
        survey=survey,
        method_name="query_probabilities",
        out_dir=out_dir,
        call=lambda: client.query_probabilities(oid, format="json", survey=survey),
    ))
    add(safe_call(
        client=client,
        survey=survey,
        method_name="query_features",
        out_dir=out_dir,
        call=lambda: client.query_features(oid, format="json", survey=survey),
    ))

    # Metadata/classifier vocabularies; not per-object source fields, but useful for mappings.
    add(safe_call(
        client=client,
        survey=survey,
        method_name="query_classifiers",
        out_dir=out_dir,
        call=lambda: client.query_classifiers(format="json", survey=survey),
    ))

    if include_heavy:
        add(safe_call(
            client=client,
            survey=survey,
            method_name="get_stamps",
            out_dir=out_dir,
            call=lambda: client.get_stamps(oid=oid, format="numpy", survey=survey),
        ))
        add(safe_call(
            client=client,
            survey=survey,
            method_name="get_avro",
            out_dir=out_dir,
            call=lambda: client.get_avro(oid=oid, use_multisurvey_api=True, survey=survey),
        ))

    if include_catshtm:
        # Try to derive coordinates from query_object payload.
        obj_path = survey_dir / "response_query_object.json"
        try:
            obj_data = json.loads(obj_path.read_text(encoding="utf-8"))
            ra = find_first_key(obj_data, RA_KEYS)
            dec = find_first_key(obj_data, DEC_KEYS)
            if ra is not None and dec is not None:
                add(safe_call(
                    client=client,
                    survey=survey,
                    method_name="catshtm_crossmatch",
                    out_dir=out_dir,
                    call=lambda: client.catshtm_crossmatch(float(ra), float(dec), 2.0, catalog_name="all", format="pandas"),
                ))
                add(safe_call(
                    client=client,
                    survey=survey,
                    method_name="catshtm_redshift",
                    out_dir=out_dir,
                    call=lambda: client.catshtm_redshift(float(ra), float(dec), 2.0, format="pandas"),
                ))
        except Exception as exc:
            write_json(survey_dir / "error_catshtm_coordinate_setup.json", {"error": str(exc)})

    # Per-survey all attributes.
    all_attrs: set[str] = set()
    rows: list[dict[str, str]] = []
    for call_result in summary["calls"]:
        method = call_result["method"]
        for attr in call_result.get("attributes", []):
            all_attrs.add(attr)
            rows.append({"survey": survey, "method": method, "attribute": attr})

    all_attrs_sorted = sorted(all_attrs)
    summary["all_attributes"] = all_attrs_sorted
    (survey_dir / "attributes_all.txt").write_text("\n".join(all_attrs_sorted) + "\n", encoding="utf-8")
    with (survey_dir / "attributes_all.tsv").open("w", encoding="utf-8") as fh:
        fh.write("survey\tmethod\tattribute\n")
        for row in sorted(rows, key=lambda r: (r["method"], r["attribute"])):
            fh.write(f"{row['survey']}\t{row['method']}\t{row['attribute']}\n")

    write_json(survey_dir / "summary.json", summary)
    return summary


def make_bundle(out_dir: Path) -> Path:
    bundle = out_dir / "alerce_payload_bundle.tar.gz"
    if bundle.exists():
        bundle.unlink()
    with tarfile.open(bundle, "w:gz") as tar:
        for path in sorted(out_dir.rglob("*")):
            if path == bundle or not path.is_file():
                continue
            tar.add(path, arcname=str(path.relative_to(out_dir.parent)))
    return bundle


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Collect ALeRCE payloads for mapping inspection.")
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Output directory. Default: data/alerce")
    p.add_argument("--surveys", nargs="+", default=DEFAULT_SURVEYS, choices=DEFAULT_SURVEYS, help="Surveys to collect.")
    p.add_argument("--ztf-id", default=None, help="Known ZTF object id, e.g. ZTF21aaeyldq")
    p.add_argument("--lsst-id", default=None, help="Known LSST object id / ALeRCE oid")
    p.add_argument("--include-heavy", action="store_true", help="Also collect stamps and avro. Can be large/slow.")
    p.add_argument("--include-catshtm", action="store_true", help="Also try catsHTM crossmatch/redshift using object coordinates.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    client = import_client()

    id_by_survey = {
        "ztf": args.ztf_id,
        "lsst": args.lsst_id,
    }

    summaries = []
    for survey in args.surveys:
        print(f"[alerce] collecting survey={survey}")
        summaries.append(
            collect_for_survey(
                client=client,
                survey=survey,
                oid=id_by_survey.get(survey),
                out_dir=args.out_dir,
                include_heavy=args.include_heavy,
                include_catshtm=args.include_catshtm,
            )
        )

    # Global attribute table.
    global_rows = []
    global_attrs = set()
    for summary in summaries:
        survey = summary["survey"]
        for call in summary.get("calls", []):
            method = call.get("method")
            for attr in call.get("attributes", []):
                global_attrs.add(f"{survey}\t{method}\t{attr}")
                global_rows.append((survey, method, attr))

    (args.out_dir / "attributes_all_surveys.tsv").write_text(
        "survey\tmethod\tattribute\n" +
        "".join(f"{s}\t{m}\t{a}\n" for s, m, a in sorted(global_rows)),
        encoding="utf-8",
    )
    write_json(args.out_dir / "payload_summary.json", {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "surveys": summaries,
    })

    bundle = make_bundle(args.out_dir)
    print(f"[alerce] wrote {args.out_dir}")
    print(f"[alerce] upload bundle: {bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
