#!/usr/bin/env python3
"""Capture representative ALeRCE/LSST evidence via the official Python client."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from client_capture import describe, finish, git_value, package_version, prepare_output, write_json

BROKER = "alerce"
SURVEY = "lsst"
DEFAULT_OID = "170587117485817955"
ENV_OID = "ALERCE_LSST_OID"
SCRIPT = Path(__file__).resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", nargs="?", help="empty output directory (default: /tmp/alerce-lsst-capture-TIMESTAMP)")
    args = parser.parse_args()
    raw_oid = os.environ.get(ENV_OID, DEFAULT_OID)
    try:
        oid = int(raw_oid)
    except ValueError:
        raise SystemExit(f"ERROR: {ENV_OID} must be an integer LSST object ID: {raw_oid!r}")
    out, captured_at = prepare_output(args.output_dir, "alerce-lsst")
    try:
        from alerce.core import Alerce
    except ImportError as exc:
        raise SystemExit("ERROR: install the repository-supported alerce client") from exc
    client = Alerce()
    methods = ["query_object", "query_detections", "query_non_detections", "query_forced_photometry", "query_lightcurve", "query_probabilities"]
    manifest = {"broker": BROKER, "survey": SURVEY, "object_id": oid, "calls": {}}
    inventory = {}
    payloads = []
    for method in methods:
        entry = {"client_method": method, "arguments": {"oid": oid, "survey": SURVEY, "format": "json"}, "endpoint_label": method}
        try:
            value = getattr(client, method)(oid=oid, survey=SURVEY, format="json")
        except NotImplementedError as exc:
            entry.update(status="not-supported", error=f"{type(exc).__name__}: {exc}")
            manifest["calls"][method] = entry
            continue
        except Exception as exc:
            entry.update(status="error", error=f"{type(exc).__name__}: {exc}")
            manifest["calls"][method] = entry
            write_json(out / "capture_manifest.json", manifest)
            raise SystemExit(f"ERROR: {method} failed: {exc}") from exc
        name = f"{method}.json"
        clean = write_json(out / name, value)
        entry["status"] = "empty" if clean in ([], {}) else "success"
        manifest["calls"][method] = entry
        inventory[method] = describe(clean)
        payloads.append(name)
    # LSST multisurvey magstats/features are known unsupported; ZTF features are omitted
    # because the audited example returns thousands of rows, too large for a minimal capture.
    manifest["calls"].update({"query_magstats": {"status": "not-supported", "endpoint_label": "query_magstats"}, "query_features": {"status": "not-supported", "endpoint_label": "query_features"}})
    write_json(out / "capture_manifest.json", manifest)
    (out / "capture_date.txt").write_text(captured_at + "\n")
    (out / "capture_metadata.txt").write_text(
        f"broker={BROKER}\nsurvey={SURVEY}\ncapture_utc={captured_at}\nscript={SCRIPT}\n"
        f"transport=python-client\nclient_package=alerce\nclient_version={package_version('alerce')}\n"
        f"primary_object_identifier={oid}\ngit_commit={git_value('rev-parse','HEAD')}\ngit_branch={git_value('branch','--show-current')}\n"
    )
    (out / "summary.txt").write_text(f"object_id={oid}\n" + "\n".join(f"{k}={v['status']}" for k,v in manifest["calls"].items()) + "\n")
    finish(out, SCRIPT, payloads, inventory)

if __name__ == "__main__":
    main()
