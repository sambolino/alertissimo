#!/usr/bin/env python3
"""Explicit live discovery acceptance through validate_dsl / execute_dsl.

--list and --validate-only make no provider calls. Live runs save final Portfolio
JSON and physical execution metadata. See docs/discovery_live_acceptance.md.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from importlib import metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import signal
import socket
import subprocess
import tempfile
import time
import traceback
from urllib.error import HTTPError, URLError

from dotenv import load_dotenv

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import MissingEndpointCredentialError
from alertissimo.orchestration.normalization import summary_object_identity


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = {
    "alerce-classification": "Original unconstrained and named-classifier ZTF lookups",
    "fink-class-time": "Original SN-candidate within 7d query; n=100 saturation fails",
    "discovery-filter-retrieve": "Short Fink class window, local real/bogus filter, survivor histories",
    "multi-object-consumer": "Two explicit Fink candidates with separate semantic evidence",
    "alerce-ztf-time": "Small cone, temporal membership, global latest, full survivor histories",
    "lasair-ztf-time": "Small cone, required summaries/history, temporal membership and latest",
    "antares-ztf-time": "Scoped RA/Dec box, complete histories, temporal membership and latest",
    "fink-cutouts": "One object, fixed JSON cutout mode, all three named stamp arrays",
}
TIME_SCENARIOS = {"alerce-ztf-time", "lasair-ztf-time", "antares-ztf-time"}
WINDOW_SCENARIOS = TIME_SCENARIOS | {"fink-class-time", "discovery-filter-retrieve"}
OBJECT_ID = "ZTF21abfmbix"
SECOND_ID = "ZTF20acpwljl"
CREDENTIAL_NAMES = ("LASAIR_ZTF_TOKEN", "LASAIR_LSST_TOKEN")


class Unexercised(RuntimeError):
    """A valid live response did not supply the data needed for this acceptance."""


def _redact(text):
    for name in CREDENTIAL_NAMES:
        value = os.environ.get(name)
        if value:
            text = text.replace(value, "<redacted>")
    return text


def _write_json(path, value):
    path.write_text(_redact(json.dumps(value, indent=2, ensure_ascii=False, default=str)) + "\n", encoding="utf-8")


def _instant(text):
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone required")
        return value.astimezone(timezone.utc)
    except ValueError as error:
        raise argparse.ArgumentTypeError("use an ISO datetime with Z or an explicit UTC offset") from error


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--require-all-pass", action="store_true", help="exit 2 if any scenario is skipped or unavailable")
    parser.add_argument("--scenario", action="append", choices=tuple(SCENARIOS))
    parser.add_argument("--start", type=_instant)
    parser.add_argument("--stop", type=_instant)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--window-hours", type=int, default=1, help="short-window scenarios only; default 1")
    parser.add_argument("--time-mode", choices=("detection", "first", "last"), default="detection",
                        help="applies only to the three *-ztf-time scenarios")
    parser.add_argument("--latest", type=int, default=3, help="candidate count for *-ztf-time; no early row limit")
    parser.add_argument("--ra", type=float, default=124.87996115142856)
    parser.add_argument("--dec", type=float, default=-6.0205001)
    parser.add_argument("--radius-arcsec", type=float, default=5.0,
                        help="cone radius; also the RA/Dec box half-width for ANTARES")
    parser.add_argument("--timeout-seconds", type=float, default=180.0, help="POSIX per-workflow live deadline")
    return parser


def _check_args(parser, args):
    if (args.start is None) != (args.stop is None):
        parser.error("--start and --stop must be paired")
    if args.start is not None and args.start > args.stop:
        parser.error("--start must not follow --stop")
    if args.window_hours <= 0 or args.latest <= 0:
        parser.error("--window-hours and --latest must be positive")
    if not math.isfinite(args.timeout_seconds) or args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be finite and positive")
    if not all(math.isfinite(v) for v in (args.ra, args.dec, args.radius_arcsec)) or args.radius_arcsec <= 0:
        parser.error("coordinates must be finite and radius must be positive")
    delta = args.radius_arcsec / 3600
    if not (0 <= args.ra - delta <= args.ra + delta < 360 and -90 <= args.dec - delta <= args.dec + delta <= 90):
        parser.error("the acceptance field must fit inside RA [0,360) and Dec [-90,90] without wrapping")


def _bounds(name, args, reference):
    if name not in WINDOW_SCENARIOS:
        return None
    duration = timedelta(days=7) if name == "fink-class-time" else timedelta(hours=args.window_hours)
    start = args.start if args.start is not None else reference - duration
    stop = args.stop if args.stop is not None else reference
    mode = args.time_mode if name in TIME_SCENARIOS else "detection"
    return {"start": start.isoformat(), "stop": stop.isoformat(), "mode": mode,
            "fixed_override": args.start is not None}


def programs(name, args):
    """Build ordinary public DSL; no physical parameters or backend assembly."""
    if name == "alerce-classification":
        return tuple(f"objects {OBJECT_ID} from ztf via alerce\nwith classification{selector} via alerce\n"
                     for selector in ("", " from lc_classifier"))
    if name == "multi-object-consumer":
        return (f"objects {OBJECT_ID}, {SECOND_ID} from ztf via fink\nwith lightcurve via fink\n",)
    if name == "fink-cutouts":
        return (f"objects {OBJECT_ID} from ztf via fink\nwith data_product via fink\n",)
    mode = args.time_mode if name in TIME_SCENARIOS else "detection"
    prefix = "" if mode == "detection" else f"{mode} "
    if args.start is not None:
        window = f'{prefix}within ["{args.start.isoformat()}", "{args.stop.isoformat()}"]\n'
    else:
        duration = "7d" if name == "fink-class-time" else f"{args.window_hours}h"
        window = f"{prefix}within {duration}\n"
    if name in {"fink-class-time", "discovery-filter-retrieve"}:
        filter_clause = "filter measurement@ztf:fink.quality.real_bogus >= 0.9\n" if name == "discovery-filter-retrieve" else ""
        return ("objects from ztf via fink\n" + window
                + 'where classification.best.class = "SN candidate"\n' + filter_clause
                + "with lightcurve via fink\nwith classification via fink\n",)
    broker = name.removesuffix("-ztf-time")
    if broker == "antares":
        delta = args.radius_arcsec / 3600
        area = (f"where summary.position.ra >= {args.ra - delta} and summary.position.ra <= {args.ra + delta} "
                f"and summary.position.dec >= {args.dec - delta} and summary.position.dec <= {args.dec + delta}\n")
    else:
        area = f"inside ({args.ra}, {args.dec}, {args.radius_arcsec}arcsec)\n"
    return (f"objects from ztf via {broker}\n{area}{window}latest {args.latest}\nwith lightcurve via {broker}\n",)


@contextmanager
def _deadline(seconds):
    # This CLI is POSIX-only for live execution. Each occurrence gets a deadline;
    # the backend's endpoint contracts and pagination policy are unchanged.
    def expired(_signum, _frame):
        raise TimeoutError(f"live workflow exceeded {seconds:g}s deadline")
    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _antares_error_status(error):
    # The pinned native client raises AntaresException(response.json()), with
    # JSON:API status codes in args[0], rather than an HTTP response attribute.
    if (type(error).__module__ != "antares_client.exceptions"
            or type(error).__name__ != "AntaresException"):
        return None
    if len(error.args) != 1:
        return "FAIL"
    payload = error.args[0]
    entries = payload.get("errors") if isinstance(payload, Mapping) else None
    if not isinstance(entries, list) or not entries:
        return "FAIL"
    codes = []
    for entry in entries:
        code = entry.get("status") if isinstance(entry, Mapping) else None
        if isinstance(code, str) and re.fullmatch(r"[45]\d{2}", code, flags=re.ASCII):
            code = int(code)
        if type(code) is not int or not 400 <= code <= 599:
            return "FAIL"
        codes.append(code)
    if all(code in (408, 429) or code >= 500 for code in codes):
        return "UNAVAILABLE"
    if all(code in (401, 403) for code in codes):
        return "SKIP"
    return "FAIL"  # Mixed/server+bad-request bodies must not hide contract errors.


def classify_error(error):
    if isinstance(error, Unexercised):
        return "SKIP"
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        native_status = _antares_error_status(current)
        if native_status is not None:
            return native_status
        response = getattr(current, "response", None)
        code = getattr(current, "code", None) or getattr(response, "status_code", None)
        if isinstance(current, MissingEndpointCredentialError) or code in (401, 403):
            return "SKIP"
        if isinstance(code, int) and (code in (408, 429) or 500 <= code <= 599):
            return "UNAVAILABLE"
        if isinstance(current, (TimeoutError, ConnectionError, socket.gaierror)):
            return "UNAVAILABLE"
        if isinstance(current, URLError) and not isinstance(current, HTTPError):
            return "UNAVAILABLE"
        if (type(current).__module__.startswith(("requests", "httpx", "urllib3"))
                and any(word in type(current).__name__.lower() for word in ("timeout", "connectionerror", "connecterror", "networkerror"))):
            return "UNAVAILABLE"
        current = current.__cause__ or current.__context__
    # Some native clients discard exception types while retaining HTTP text.
    message = str(error)
    if re.search(r"HTTP(?: Error|Error:)?\s+(?:401|403)\b", message, re.I):
        return "SKIP"
    if re.search(r"HTTP(?: Error|Error:)?\s+(?:408|429|5\d\d)\b|gateway (?:time-out|timeout)", message, re.I):
        return "UNAVAILABLE"
    return "FAIL"  # Includes saturation, invalid material, and planning defects.


def _identities(portfolios):
    identities = [summary_object_identity(p) for p in portfolios]
    if None in identities or len(identities) != len(set(identities)):
        raise RuntimeError("final Portfolios have missing, ambiguous, or duplicate candidate identities")
    return set(identities)


def _execution_evidence(result):
    evidence = []
    for step in result.staged.execution.steps:
        for execution in step.executions:
            p = execution.execution_provenance
            evidence.append({"step_index": step.step_index, "execution_id": p.internal_execution_id.value,
                             "broker": p.broker, "origin": p.origin, "endpoint": p.endpoint,
                             "params": dict(p.params), "status": p.status, "elapsed_ms": p.elapsed_ms,
                             "response_status_code": p.response_status_code,
                             "response_content_type": p.response_content_type,
                             "raw_size_bytes": p.raw_size_bytes})
    return evidence


def _assert_result(name, result, args, program_index):
    if any(step.state.value != "succeeded" for step in result.run.steps):
        raise RuntimeError("workflow did not complete every semantic Step")
    final = _identities(result.portfolios)
    if any(origin != "ztf" for origin, _ in final):
        raise RuntimeError("ZTF acceptance returned foreign-survey candidates")
    if name in {"alerce-classification", "fink-cutouts"} and final - {("ztf", OBJECT_ID)}:
        raise RuntimeError("explicit lookup returned another object's material")
    if name == "multi-object-consumer" and final - {("ztf", OBJECT_ID), ("ztf", SECOND_ID)}:
        raise RuntimeError("multi-object lookup returned unexpected identities")
    if not final:
        raise Unexercised("valid empty result; no nonempty live acceptance established")
    if any(step.warnings for step in result.run.steps):
        raise Unexercised("optional supplementary evidence incomplete; saved result retains warnings")
    if name == "alerce-classification":
        if final != {("ztf", OBJECT_ID)}:
            raise RuntimeError("classification lookup lost its candidate")
        classes = [r for p in result.portfolios for r in p.records if r.semantic_type.startswith("classification@")]
        if not classes:
            raise Unexercised("no classification assertions returned for this object")
        if program_index == 1 and any(r.semantic_type != "classification@lc_classifier:alerce" for r in classes):
            raise RuntimeError("named classifier selection retained a different producer")
    elif name == "multi-object-consumer":
        if final != {("ztf", OBJECT_ID), ("ztf", SECOND_ID)}:
            raise Unexercised("provider did not return both requested objects")
        source_ids = set()
        for p in result.portfolios:
            oid = summary_object_identity(p)[1]
            measurements = p.records_of_type("measurement@ztf:fink")
            if not measurements:
                raise Unexercised(f"no Fink measurements for {oid}")
            if any(r.has("identity.object_id") and str(r.get("identity.object_id")) != oid for r in measurements):
                raise RuntimeError("measurement ownership differs from its candidate Portfolio")
            ids = {r.get("identity.source_id") for r in measurements if r.get("identity.source_id") is not None}
            if not ids:
                raise Unexercised(f"no identified Fink detections for {oid}")
            if ids & source_ids:
                raise RuntimeError("different objects share Fink detection identities")
            source_ids.update(ids)
    elif name == "fink-cutouts":
        products = [r for p in result.portfolios for r in p.records_of_type("data_product@ztf:fink")]
        if not products or any(set(r.get("payload", {})) != {"science", "template", "difference"} for r in products):
            raise RuntimeError("cutout product does not retain all three named arrays")
    else:
        discovered = _identities(result.result.steps[0].portfolios)
        if not final <= discovered:
            raise RuntimeError("retrieval resurrected an undiscovered or rejected candidate")
        if name == "discovery-filter-retrieve":
            filter_index, = [i for i, step in enumerate(result.workflow.steps) if step.op == "filter"]
            if final != _identities(result.result.steps[filter_index].portfolios):
                raise RuntimeError("final retrieval differs from Filter survivors")
        if name in TIME_SCENARIOS and len(final) > args.latest:
            raise RuntimeError("latest returned more candidates than requested")
        if not any(r.semantic_type.startswith("lightcurve@") for p in result.portfolios for r in p.records):
            raise Unexercised("no returned lightcurve material; retrieval acceptance unexercised")


def _revision():
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _versions():
    result = {"python": platform.python_version()}
    for name in ("alertissimo", "alerce", "antares-client", "lark", "pydantic", "PyYAML"):
        try:
            result[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            result[name] = "not installed as a distribution"
    return result


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    _check_args(parser, args)
    if args.list:
        for name, description in SCENARIOS.items():
            print(f"{name:28} {description}")
        return 0
    if not args.validate_only and not hasattr(signal, "setitimer"):
        parser.error("live execution requires POSIX timers for the per-workflow deadline")
    selected = tuple(dict.fromkeys(args.scenario or SCENARIOS))
    if args.start is not None and not set(selected) & WINDOW_SCENARIOS:
        parser.error("fixed bounds require at least one windowed scenario")
    load_dotenv(ROOT / ".env", override=False)
    reference = datetime.now(timezone.utc)
    output = args.output_dir.resolve() if args.output_dir else Path(tempfile.mkdtemp(prefix="alertissimo-discovery-"))
    # Never overwrite evidence from an earlier invocation.
    if output.exists() and any(output.iterdir()):
        parser.error("--output-dir must be new or empty; choose a separate directory for each run")
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"revision": _revision(), "versions": _versions(), "reference_time": reference.isoformat(),
                "validate_only": args.validate_only, "options": vars(args), "scenarios": list(selected),
                "results": []}
    _write_json(output / "run.json", manifest)
    print(f"Evidence: {output}")
    for name in selected:
        directory = output / name
        directory.mkdir()
        started = time.monotonic()
        record = {"scenario": name, "status": "PASS", "phase": "validation" if args.validate_only else "live",
                  "resolved_bounds": _bounds(name, args, reference), "programs": []}
        try:
            for index, source in enumerate(programs(name, args)):
                (directory / f"{index:02d}.dsl").write_text(source, encoding="utf-8")
                validation = validate_dsl(source, continue_from=None)
                if not validation.is_runnable:
                    raise RuntimeError(f"validate_dsl rejected scenario: {validation.parse_error or validation.lowering_error or validation.semantic}")
                item = {"source_file": f"{index:02d}.dsl", "planned": True}
                record["programs"].append(item)
                if args.validate_only:
                    continue
                with _deadline(args.timeout_seconds):
                    result = execute_dsl(source, continue_from=None, reference_time=reference)
                _write_json(directory / f"{index:02d}.result.json", result.to_dict())
                executions = _execution_evidence(result)
                item.update({"result_file": f"{index:02d}.result.json", "executions": executions,
                             "unique_physical_executions": len({e["execution_id"] for e in executions}),
                             "candidate_identities": sorted(_identities(result.portfolios)),
                             "candidate_count": len(result.portfolios),
                             "record_count": sum(len(p.records) for p in result.portfolios),
                             "step_candidate_counts": [len(s.portfolios) for s in result.result.steps]})
                _assert_result(name, result, args, index)
            record["detail"] = "offline planning only; no provider calls" if args.validate_only else "nonempty live workflow and scenario invariants passed"
        except Exception as error:
            record.update(status=classify_error(error), detail=_redact(f"{type(error).__name__}: {error}"))
            (directory / "error.log").write_text(_redact(traceback.format_exc()), encoding="utf-8")
        record["elapsed_seconds"] = round(time.monotonic() - started, 3)
        _write_json(directory / "summary.json", record)
        manifest["results"].append(record)
        _write_json(output / "run.json", manifest)
        print(f"{record['status']:12} {name:28} {record['detail']}", flush=True)
    counts = Counter(r["status"] for r in manifest["results"])
    print("Summary: " + ", ".join(f"{key}={counts[key]}" for key in ("PASS", "FAIL", "UNAVAILABLE", "SKIP")))
    # A diagnostic sweep can finish with outages, but an all-green acceptance
    # requires status PASS for every scenario, not merely exit status zero.
    if counts["FAIL"]:
        return 1
    return 2 if args.require_all_pass and (counts["SKIP"] or counts["UNAVAILABLE"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
