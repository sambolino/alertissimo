#!/usr/bin/env python3
"""
Collect ALeRCE live payloads + declared response schemas for Alertissimo mapping work.

This script is intentionally practical, not clever:
- It calls the ALeRCE Python client and saves raw-ish payloads.
- It retries object-dependent methods over discovered candidate OIDs when payloads are empty.
- It fetches/parses ALeRCE GitHub docs/source/models/*.rst as declared response schemas.
- It writes a comparison report showing documented fields, observed fields, empty payloads,
  and known/not-implemented multisurvey methods.
- It creates one tar.gz bundle you can upload.

Typical runs:
  python3 data/collect_alerce_schema_payload_audit.py --ztf-id ZTF21aaeyldq --max-candidates 500
  python3 data/collect_alerce_schema_payload_audit.py --ztf-id ZTF21aaeyldq --max-candidates 500 --include-heavy
  python3 data/collect_alerce_schema_payload_audit.py --surveys lsst --max-candidates 1000

Dependencies:
  pip install alerce

Optional, only if you want pandas/astropy output conversions in the client:
  pip install pandas astropy
"""

from __future__ import annotations

import argparse
import json
import re
import tarfile
import traceback
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_OUT_DIR = Path("data/alerce_schema_payload_audit")
DEFAULT_SURVEYS = ["ztf", "lsst"]
GITHUB_OWNER_REPO = "alercebroker/alerce_client"

MODEL_FILES = [
    "object",
    "detection",
    "ztf_detection",
    "lsst_detection",
    "non_detection",
    "forced_photometry",
    "ztf_forced_photometry",
    "lsst_forced_photometry",
    "probability",
    "magstats",
]

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

# These are current client/backend limitations observed in ALeRCE multisurvey code.
# We still attach declared schemas where available, so mappings can include declared
# attributes while endpoints can mark the method as disabled/unsupported.
KNOWN_UNSUPPORTED = {
    ("lsst", "query_magstats"): "Multisurvey query_magstats not implemented in current ALeRCE client/backend.",
    ("lsst", "query_features"): "Multisurvey query_features not implemented in current ALeRCE client/backend.",
    ("lsst", "query_classifiers"): "Multisurvey query_classifiers not implemented in current ALeRCE client/backend.",
}

# The docs do not expose a method-by-method OpenAPI schema. These bindings connect
# client methods to documented response models where the docs provide one.
METHOD_MODELS = {
    "query_objects": {
        "ztf": ["object"],
        "lsst": ["object"],
    },
    "query_object": {
        "ztf": ["object"],
        "lsst": ["object"],
    },
    "query_detections": {
        "ztf": ["ztf_detection"],
        "lsst": ["lsst_detection"],
    },
    "query_non_detections": {
        "ztf": ["non_detection"],
        "lsst": ["non_detection"],
    },
    "query_forced_photometry": {
        "ztf": ["ztf_forced_photometry", "forced_photometry"],
        "lsst": ["lsst_forced_photometry", "forced_photometry"],
    },
    "query_lightcurve": {
        "ztf": ["ztf_detection", "non_detection", "ztf_forced_photometry"],
        "lsst": ["lsst_detection", "non_detection", "lsst_forced_photometry"],
    },
    "query_magstats": {
        "ztf": ["magstats"],
        "lsst": ["magstats"],
    },
    "query_probabilities": {
        "ztf": ["probability"],
        "lsst": ["probability"],
    },
    # query_features and query_classifiers are intentionally left without docs models.
    # ZTF can still provide observed fields from live payloads.
}


@dataclass
class FieldSpec:
    name: str
    type: str | None
    description: str | None


@dataclass
class MethodAudit:
    survey: str
    method: str
    status: str
    selected_oid: str | None
    selected_response_file: str | None
    attempts_file: str | None
    documented_models: list[str]
    documented_fields: list[str]
    observed_top_level_fields: list[str]
    observed_flattened_fields: list[str]
    note: str | None = None
    error: str | None = None


def json_default(obj: Any) -> Any:
    """Serialize common scientific Python objects conservatively."""
    if obj is None:
        return None

    # pandas DataFrame / Series
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
            "preview_hex": bytes(obj[:64]).hex(),
        }

    if isinstance(obj, (set, tuple)):
        return list(obj)

    return str(obj)


def to_jsonable(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=json_default, ensure_ascii=False))


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(data), indent=2, ensure_ascii=False), encoding="utf-8")


def save_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fetch_url_text(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "alertissimo-schema-audit/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def get_doc_text(model_name: str, args: argparse.Namespace) -> tuple[str | None, str]:
    """Read model .rst from local repo path or GitHub raw."""
    rel = Path("docs/source/models") / f"{model_name}.rst"

    if args.alerce_repo_path:
        local_path = Path(args.alerce_repo_path) / rel
        if local_path.exists():
            return local_path.read_text(encoding="utf-8"), str(local_path)

    if args.no_fetch_docs:
        return None, "docs fetching disabled"

    url = f"https://raw.githubusercontent.com/{GITHUB_OWNER_REPO}/{args.github_ref}/{rel.as_posix()}"
    try:
        return fetch_url_text(url, timeout=args.github_timeout), url
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return None, f"{url} :: {exc!r}"


def normalize_cell(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def parse_rst_list_table_fields(text: str) -> list[FieldSpec]:
    """Parse the simple Sphinx list-table format used in docs/source/models/*.rst."""
    rows: list[list[str]] = []
    current: list[str] | None = None

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith(".. ") or stripped.startswith(":"):
            continue

        if stripped.startswith("* - "):
            if current is not None:
                rows.append(current)
            current = [stripped[4:].strip()]
            continue

        if current is not None and stripped.startswith("- "):
            current.append(stripped[2:].strip())
            continue

        # Continuation of previous cell description.
        if current is not None and current:
            current[-1] = f"{current[-1]} {stripped}".strip()

    if current is not None:
        rows.append(current)

    fields: list[FieldSpec] = []
    for row in rows:
        if len(row) < 3:
            continue
        name, typ, desc = normalize_cell(row[0]), normalize_cell(row[1]), normalize_cell(" ".join(row[2:]))
        if name.lower() == "name" and typ.lower() == "type":
            continue
        if not name or name.startswith("*"):
            continue
        fields.append(FieldSpec(name=name, type=typ or None, description=desc or None))

    return fields


def collect_declared_schemas(args: argparse.Namespace, out_dir: Path) -> dict[str, dict[str, Any]]:
    declared: dict[str, dict[str, Any]] = {}
    docs_dir = out_dir / "declared_docs"

    for model_name in MODEL_FILES:
        text, source = get_doc_text(model_name, args)
        if text is None:
            declared[model_name] = {"source": source, "status": "missing", "fields": []}
            continue
        save_text(docs_dir / f"{model_name}.rst", text)
        fields = parse_rst_list_table_fields(text)
        declared[model_name] = {
            "source": source,
            "status": "ok",
            "fields": [asdict(f) for f in fields],
            "field_names": [f.name for f in fields],
        }
        save_json(out_dir / "declared_schemas" / f"{model_name}.json", declared[model_name])

    save_json(out_dir / "declared_schemas" / "all_models.json", declared)

    lines = ["model\tfield\ttype\tdescription\tsource"]
    for model_name, model in declared.items():
        for field in model.get("fields", []):
            lines.append("\t".join([
                model_name,
                str(field.get("name", "")).replace("\t", " "),
                str(field.get("type", "")).replace("\t", " "),
                str(field.get("description", "")).replace("\t", " "),
                str(model.get("source", "")).replace("\t", " "),
            ]))
    save_text(out_dir / "declared_schema_fields.tsv", "\n".join(lines) + "\n")
    return declared


def documented_models_for(survey: str, method: str) -> list[str]:
    return list(METHOD_MODELS.get(method, {}).get(survey, []))


def documented_fields_for(declared: dict[str, dict[str, Any]], survey: str, method: str) -> list[str]:
    fields: list[str] = []
    for model_name in documented_models_for(survey, method):
        for field_name in declared.get(model_name, {}).get("field_names", []):
            if field_name not in fields:
                fields.append(field_name)
    return fields


def is_empty_payload(obj: Any) -> bool:
    obj = to_jsonable(obj)

    if obj is None:
        return True
    if isinstance(obj, list):
        return len(obj) == 0
    if isinstance(obj, dict):
        if not obj:
            return True
        # Common lightcurve shape. Empty only if all components are empty.
        lightcurve_keys = {"detections", "non_detections", "forced_photometry"}
        if set(obj.keys()).issubset(lightcurve_keys):
            return all(is_empty_payload(v) for v in obj.values())
        if "error" in obj and len(obj) <= 4:
            return True
        return False
    if isinstance(obj, str):
        return obj.strip() == ""
    return False


def flatten_fields(obj: Any, prefix: str = "") -> set[str]:
    obj = to_jsonable(obj)
    fields: set[str] = set()

    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            fields.add(path)
            fields |= flatten_fields(value, path)
    elif isinstance(obj, list):
        for item in obj[:50]:
            fields |= flatten_fields(item, prefix)

    return fields


def top_level_fields(obj: Any) -> set[str]:
    obj = to_jsonable(obj)
    fields: set[str] = set()

    if isinstance(obj, dict):
        # Preserve component prefix for compound payloads like lightcurve.
        for key, value in obj.items():
            if isinstance(value, list):
                subfields = set()
                for item in value[:50]:
                    if isinstance(item, dict):
                        subfields.update(str(k) for k in item.keys())
                if subfields:
                    fields.update(f"{key}.{sf}" for sf in sorted(subfields))
                else:
                    fields.add(key)
            elif isinstance(value, dict):
                fields.add(key)
                fields.update(f"{key}.{sf}" for sf in value.keys())
            else:
                fields.add(key)
    elif isinstance(obj, list):
        for item in obj[:50]:
            if isinstance(item, dict):
                fields.update(str(k) for k in item.keys())

    return fields


def find_oid_candidates(obj: Any) -> list[str]:
    obj = to_jsonable(obj)
    keys = ["oid", "objectId", "object_id", "diaObjectId", "dia_object_id", "aid", "id"]
    found: list[str] = []

    def visit(x: Any) -> None:
        if isinstance(x, dict):
            for k in keys:
                if k in x and x[k] not in (None, ""):
                    value = str(x[k])
                    if value not in found:
                        found.append(value)
            for v in x.values():
                visit(v)
        elif isinstance(x, list):
            for item in x:
                visit(item)

    visit(obj)
    return found


def find_position(obj: Any) -> tuple[float, float] | None:
    """Find a reasonable RA/Dec pair from any payload for catsHTM calls."""
    obj = to_jsonable(obj)
    ra_keys = ["ra", "meanra", "raMean", "coord_ra"]
    dec_keys = ["dec", "meandec", "decMean", "coord_dec"]

    def as_float(v: Any) -> float | None:
        try:
            f = float(v)
            if f == f:  # not NaN
                return f
        except Exception:
            return None
        return None

    def visit(x: Any) -> tuple[float, float] | None:
        if isinstance(x, dict):
            for rk in ra_keys:
                for dk in dec_keys:
                    if rk in x and dk in x:
                        ra = as_float(x[rk])
                        dec = as_float(x[dk])
                        if ra is not None and dec is not None:
                            return ra, dec
            for v in x.values():
                pos = visit(v)
                if pos is not None:
                    return pos
        elif isinstance(x, list):
            for item in x:
                pos = visit(item)
                if pos is not None:
                    return pos
        return None

    return visit(obj)


def call_client_method(client: Any, method: str, survey: str, oid: str | None = None) -> Any:
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

    raise ValueError(f"Unknown method: {method}")


def discover_candidates(client: Any, survey: str, max_candidates: int, out_dir: Path) -> list[str]:
    attempts: list[dict[str, Any]] = []
    variants = [
        {"format": "json", "survey": survey, "page_size": max_candidates, "count": False},
        {"format": "json", "survey": survey, "page_size": max_candidates},
        {"format": "json", "survey": survey},
    ]

    for params in variants:
        try:
            resp = client.query_objects(**params)
            data = to_jsonable(resp)
            oids = find_oid_candidates(data)
            attempts.append({"params": params, "status": "ok", "n_oids": len(oids), "oids": oids[:max_candidates]})
            save_json(out_dir / survey / "response_query_objects_discovery.json", data)
            save_json(out_dir / survey / "response_query_objects_discovery_attempts.json", attempts)
            if oids:
                return oids[:max_candidates]
        except Exception as exc:
            attempts.append({"params": params, "status": "error", "error": repr(exc), "traceback": traceback.format_exc()})

    save_json(out_dir / survey / "response_query_objects_discovery_attempts.json", attempts)
    return []


def collect_method(
    client: Any,
    survey: str,
    method: str,
    candidates: list[str],
    declared: dict[str, dict[str, Any]],
    out_dir: Path,
    retry_empty: bool,
    try_unsupported: bool,
) -> MethodAudit:
    survey_dir = out_dir / survey
    survey_dir.mkdir(parents=True, exist_ok=True)

    doc_models = documented_models_for(survey, method)
    doc_fields = documented_fields_for(declared, survey, method)

    if (survey, method) in KNOWN_UNSUPPORTED and not try_unsupported:
        attempts_file = survey_dir / f"response_{method}_attempts.json"
        save_json(attempts_file, [{
            "status": "known_unsupported",
            "note": KNOWN_UNSUPPORTED[(survey, method)],
            "documented_models": doc_models,
            "documented_fields": doc_fields,
        }])
        return MethodAudit(
            survey=survey,
            method=method,
            status="known_unsupported",
            selected_oid=None,
            selected_response_file=None,
            attempts_file=str(attempts_file),
            documented_models=doc_models,
            documented_fields=doc_fields,
            observed_top_level_fields=[],
            observed_flattened_fields=[],
            note=KNOWN_UNSUPPORTED[(survey, method)],
        )

    object_method = method in OBJECT_METHODS or method in HEAVY_OBJECT_METHODS
    oids_to_try = candidates if object_method else [None]
    if object_method and not retry_empty:
        oids_to_try = candidates[:1]

    attempts: list[dict[str, Any]] = []
    selected_payload: Any = None
    selected_oid: str | None = None
    selected_file: str | None = None
    status = "empty"
    error: str | None = None

    if object_method and not oids_to_try:
        status = "no_candidate_oid"
        attempts.append({"status": status, "note": "No candidate object IDs available."})

    for i, oid in enumerate(oids_to_try, start=1):
        try:
            resp = call_client_method(client, method, survey, oid=oid)
            data = to_jsonable(resp)
            empty = is_empty_payload(data)
            attempt_file = survey_dir / f"response_{method}_attempt_{i:03d}.json"
            save_json(attempt_file, data)
            attempts.append({
                "attempt": i,
                "oid": oid,
                "status": "ok_empty" if empty else "ok_non_empty",
                "file": str(attempt_file),
                "top_level_fields": sorted(top_level_fields(data)),
                "flattened_fields": sorted(flatten_fields(data))[:1000],
            })

            if not empty:
                selected_payload = data
                selected_oid = oid
                selected_file = str(attempt_file)
                status = "ok"
                break

            # Keep the first empty payload as selected if nothing better appears.
            if selected_payload is None:
                selected_payload = data
                selected_oid = oid
                selected_file = str(attempt_file)
                status = "empty"

            if not retry_empty:
                break

        except NotImplementedError as exc:
            status = "not_implemented"
            error = repr(exc)
            attempts.append({"attempt": i, "oid": oid, "status": status, "error": error, "traceback": traceback.format_exc()})
            break
        except Exception as exc:
            error = repr(exc)
            attempts.append({"attempt": i, "oid": oid, "status": "error", "error": error, "traceback": traceback.format_exc()})
            # Try next candidate for object-specific data; stop for global methods.
            if not object_method:
                status = "error"
                break

    attempts_file = survey_dir / f"response_{method}_attempts.json"
    save_json(attempts_file, attempts)

    canonical_file: str | None = None
    observed_top: list[str] = []
    observed_flat: list[str] = []
    if selected_payload is not None:
        canonical_path = survey_dir / f"response_{method}.json"
        save_json(canonical_path, selected_payload)
        canonical_file = str(canonical_path)
        observed_top = sorted(top_level_fields(selected_payload))
        observed_flat = sorted(flatten_fields(selected_payload))

    # If selected_file exists but canonical could not be written, keep selected_file.
    if canonical_file is None and selected_file:
        canonical_file = selected_file

    return MethodAudit(
        survey=survey,
        method=method,
        status=status,
        selected_oid=selected_oid,
        selected_response_file=canonical_file,
        attempts_file=str(attempts_file),
        documented_models=doc_models,
        documented_fields=doc_fields,
        observed_top_level_fields=observed_top,
        observed_flattened_fields=observed_flat,
        error=error,
    )


def collect_catshtm(client: Any, out_dir: Path, audits: list[MethodAudit], radius: float, catalog_name: str) -> dict[str, Any]:
    """Optional coordinate-based catsHTM probe. This is not survey-specific."""
    # Find a saved payload with a position.
    position = None
    source_file = None
    for audit in audits:
        if audit.selected_response_file:
            try:
                data = json.loads(Path(audit.selected_response_file).read_text(encoding="utf-8"))
                pos = find_position(data)
                if pos:
                    position = pos
                    source_file = audit.selected_response_file
                    break
            except Exception:
                continue

    cats_dir = out_dir / "catshtm"
    cats_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"status": "not_run", "position": position, "source_file": source_file}

    if position is None:
        result["status"] = "no_position_found"
        save_json(cats_dir / "catshtm_summary.json", result)
        return result

    ra, dec = position
    calls = [
        ("catshtm_conesearch", lambda: client.catshtm_conesearch(ra=ra, dec=dec, radius=radius, catalog_name=catalog_name, format="pandas")),
        ("catshtm_crossmatch", lambda: client.catshtm_crossmatch(ra=ra, dec=dec, radius=radius, catalog_name=catalog_name, format="pandas")),
        ("catshtm_redshift", lambda: client.catshtm_redshift(ra=ra, dec=dec, radius=radius, format="pandas")),
    ]

    result.update({"status": "ok", "ra": ra, "dec": dec, "radius_arcsec": radius, "catalog_name": catalog_name, "calls": {}})
    for name, fn in calls:
        try:
            data = to_jsonable(fn())
            path = cats_dir / f"response_{name}.json"
            save_json(path, data)
            result["calls"][name] = {
                "status": "empty" if is_empty_payload(data) else "ok",
                "file": str(path),
                "top_level_fields": sorted(top_level_fields(data)),
                "flattened_fields": sorted(flatten_fields(data))[:1000],
            }
        except Exception as exc:
            result["calls"][name] = {"status": "error", "error": repr(exc), "traceback": traceback.format_exc()}

    save_json(cats_dir / "catshtm_summary.json", result)
    return result


def write_tables(out_dir: Path, audits: list[MethodAudit], declared: dict[str, dict[str, Any]]) -> None:
    # Method audit table.
    lines = [
        "survey\tmethod\tstatus\tselected_oid\tdocumented_models\tdocumented_field_count\tobserved_top_field_count\tobserved_flat_field_count\tnote\terror"
    ]
    for a in audits:
        lines.append("\t".join([
            a.survey,
            a.method,
            a.status,
            a.selected_oid or "",
            ",".join(a.documented_models),
            str(len(a.documented_fields)),
            str(len(a.observed_top_level_fields)),
            str(len(a.observed_flattened_fields)),
            (a.note or "").replace("\t", " "),
            (a.error or "").replace("\t", " "),
        ]))
    save_text(out_dir / "method_audit.tsv", "\n".join(lines) + "\n")

    # Field comparison table. This is the key file for mapping work.
    comp = ["survey\tmethod\tfield\tin_docs\tin_payload_top\tin_payload_flat\tdocumented_models\tmethod_status"]
    for a in audits:
        doc = set(a.documented_fields)
        top = set(a.observed_top_level_fields)
        flat = set(a.observed_flattened_fields)
        all_fields = sorted(doc | top | flat)
        for field in all_fields:
            comp.append("\t".join([
                a.survey,
                a.method,
                field.replace("\t", " "),
                "1" if field in doc else "0",
                "1" if field in top else "0",
                "1" if field in flat else "0",
                ",".join(a.documented_models),
                a.status,
            ]))
    save_text(out_dir / "field_comparison.tsv", "\n".join(comp) + "\n")

    # Declared model fields, already written by collect_declared_schemas, but also write compact names.
    names = ["model\tfield"]
    for model_name, model in declared.items():
        for field in model.get("field_names", []):
            names.append(f"{model_name}\t{field}")
    save_text(out_dir / "declared_field_names.tsv", "\n".join(names) + "\n")


def write_markdown_report(out_dir: Path, audits: list[MethodAudit], catshtm_summary: dict[str, Any] | None) -> None:
    lines: list[str] = []
    lines.append("# ALeRCE schema/payload audit")
    lines.append("")
    lines.append("This report combines declared response schemas from ALeRCE documentation with live payload samples collected through the ALeRCE Python client.")
    lines.append("")
    lines.append("## Method status")
    lines.append("")
    lines.append("| Survey | Method | Status | OID | Docs models | Docs fields | Payload top fields | Note |")
    lines.append("|---|---|---:|---|---|---:|---:|---|")
    for a in audits:
        lines.append(
            f"| {a.survey} | `{a.method}` | {a.status} | {a.selected_oid or ''} | {', '.join(a.documented_models)} | {len(a.documented_fields)} | {len(a.observed_top_level_fields)} | {(a.note or a.error or '').replace('|', '/')} |"
        )

    lines.append("")
    lines.append("## Mapping guidance")
    lines.append("")
    lines.append("Use `field_comparison.tsv` as the main mapping input:")
    lines.append("")
    lines.append("- `in_docs=1` and `in_payload_top=1`: safest mapping candidates.")
    lines.append("- `in_docs=1` and method status `known_unsupported` or `not_implemented`: declared attributes; include in mappings if desired, but mark endpoint unsupported/disabled.")
    lines.append("- `in_docs=1` and payload empty: declared attributes; endpoint is implemented, but current samples did not expose rows.")
    lines.append("- `in_payload_top=1` and `in_docs=0`: live-only attributes; map only when meaning is clear.")
    lines.append("")

    if catshtm_summary is not None:
        lines.append("## catsHTM")
        lines.append("")
        lines.append(f"Status: `{catshtm_summary.get('status')}`")
        if catshtm_summary.get("position"):
            lines.append(f"Position: `{catshtm_summary.get('position')}` from `{catshtm_summary.get('source_file')}`")
        lines.append("")

    save_text(out_dir / "schema_payload_audit_report.md", "\n".join(lines) + "\n")


def make_bundle(out_dir: Path) -> Path:
    bundle = out_dir / "alerce_schema_payload_audit_bundle.tar.gz"
    with tarfile.open(bundle, "w:gz") as tar:
        for path in sorted(out_dir.rglob("*")):
            if path == bundle or path.is_dir():
                continue
            tar.add(path, arcname=str(path))
    return bundle


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect ALeRCE declared schemas + live payloads for Alertissimo mappings.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory. Default: data/alerce_schema_payload_audit")
    parser.add_argument("--surveys", nargs="+", choices=DEFAULT_SURVEYS, default=DEFAULT_SURVEYS)
    parser.add_argument("--ztf-id", default=None, help="Preferred ZTF object ID.")
    parser.add_argument("--lsst-id", default=None, help="Preferred LSST object ID.")
    parser.add_argument("--max-candidates", type=int, default=100, help="Max candidate OIDs per survey. Default: 100")
    parser.add_argument("--no-retry-empty", action="store_true", help="Do not retry object methods when payload is empty.")
    parser.add_argument("--try-unsupported", action="store_true", help="Actually call known unsupported multisurvey methods instead of marking them.")
    parser.add_argument("--include-heavy", action="store_true", help="Include get_stamps and get_avro. Can be large/slow/fail.")
    parser.add_argument("--include-catshtm", action="store_true", help="Probe catsHTM crossmatch/conesearch/redshift using the first RA/Dec found in payloads.")
    parser.add_argument("--catshtm-radius", type=float, default=2.0, help="catsHTM radius in arcsec. Default: 2.0")
    parser.add_argument("--catshtm-catalog", default="all", help="catsHTM catalog_name. Default: all")
    parser.add_argument("--alerce-repo-path", default=None, help="Optional local clone of alercebroker/alerce_client for docs/source/models/*.rst")
    parser.add_argument("--github-ref", default="main", help="GitHub ref for fetching docs. Default: main")
    parser.add_argument("--github-timeout", type=int, default=30, help="Timeout seconds for GitHub raw docs. Default: 30")
    parser.add_argument("--no-fetch-docs", action="store_true", help="Disable GitHub docs fetching; use only --alerce-repo-path if provided.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from alerce.core import Alerce
    except Exception as exc:
        raise SystemExit(
            "Could not import the ALeRCE client. Install it with:\n"
            "  pip install alerce\n"
            f"Original error: {exc!r}"
        )

    print("Collecting declared ALeRCE schemas from docs/source/models/*.rst ...")
    declared = collect_declared_schemas(args, out_dir)
    declared_ok = sum(1 for m in declared.values() if m.get("status") == "ok")
    print(f"Declared models fetched/parsed: {declared_ok}/{len(MODEL_FILES)}")

    client = Alerce()
    preferred_ids = {"ztf": args.ztf_id, "lsst": args.lsst_id}
    methods = list(GLOBAL_METHODS) + list(OBJECT_METHODS)
    if args.include_heavy:
        methods += HEAVY_OBJECT_METHODS

    audits: list[MethodAudit] = []
    summary: dict[str, Any] = {
        "script": "collect_alerce_schema_payload_audit.py",
        "surveys": args.surveys,
        "max_candidates": args.max_candidates,
        "retry_empty": not args.no_retry_empty,
        "include_heavy": args.include_heavy,
        "include_catshtm": args.include_catshtm,
        "known_unsupported": {f"{s}/{m}": reason for (s, m), reason in KNOWN_UNSUPPORTED.items()},
        "declared_models_status": {name: model.get("status") for name, model in declared.items()},
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

        summary["surveys_detail"][survey] = {"candidate_count": len(candidates), "candidates": candidates, "methods": {}}

        for method in methods:
            print(f"  {method} ...", end="", flush=True)
            audit = collect_method(
                client=client,
                survey=survey,
                method=method,
                candidates=candidates,
                declared=declared,
                out_dir=out_dir,
                retry_empty=not args.no_retry_empty,
                try_unsupported=args.try_unsupported,
            )
            audits.append(audit)
            summary["surveys_detail"][survey]["methods"][method] = asdict(audit)
            print(f" {audit.status}" + (f" oid={audit.selected_oid}" if audit.selected_oid else ""))

    catshtm_summary = None
    if args.include_catshtm:
        print("\n=== catsHTM ===")
        catshtm_summary = collect_catshtm(
            client=client,
            out_dir=out_dir,
            audits=audits,
            radius=args.catshtm_radius,
            catalog_name=args.catshtm_catalog,
        )
        print(catshtm_summary.get("status"))
        summary["catshtm"] = catshtm_summary

    save_json(out_dir / "payload_schema_summary.json", summary)
    save_json(out_dir / "method_audits.json", [asdict(a) for a in audits])
    write_tables(out_dir, audits, declared)
    write_markdown_report(out_dir, audits, catshtm_summary)
    bundle = make_bundle(out_dir)

    print("\nWrote:")
    print(f"  {out_dir / 'payload_schema_summary.json'}")
    print(f"  {out_dir / 'method_audit.tsv'}")
    print(f"  {out_dir / 'field_comparison.tsv'}")
    print(f"  {out_dir / 'declared_schema_fields.tsv'}")
    print(f"  {out_dir / 'schema_payload_audit_report.md'}")
    print(f"  {bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
