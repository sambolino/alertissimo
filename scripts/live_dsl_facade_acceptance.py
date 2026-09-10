#!/usr/bin/env python3
"""Run every registered live DSL acceptance workflow through the public facade.

This is a facade sweep, not a replacement for the scenario-specific acceptance
scripts. It replays the same default DSL workflows through exactly the public path:

    validate_dsl(source)
    execute_dsl(source)
    execution.to_json()

Programmatic-IR, presentation, and offline-control scenarios from
``scripts/live_acceptance.py`` are excluded because they have no DSL input.
"""

from __future__ import annotations

import argparse
import cProfile
from dataclasses import dataclass
import json
import os
from pathlib import Path
import pstats
import re
from time import monotonic
from typing import Literal

from dotenv import load_dotenv

from alertissimo.api import execute_dsl, validate_dsl


REPO_ROOT = Path(__file__).resolve().parents[1]
Status = Literal["PASS", "UNAVAILABLE", "SKIP", "FAIL"]


@dataclass(frozen=True)
class FacadeScenario:
    name: str
    source: str
    required_env: tuple[str, ...] = ()


CLASSIFIER = "stamp_classifier_rubin_beta_20260421"
LSST_SAMPLE_RA = 62.45763123249455
LSST_SAMPLE_DEC = -48.481492749718534
LSST_SAMPLE_RADIUS_ARCSEC = 1.0

SCENARIOS = (
    FacadeScenario(
        "multisurvey-discovery",
        """objects from lsst, ztf via alerce
inside (305.5822327501884, -18.7909207179724, 300.0arcsec)
""",
    ),
    FacadeScenario(
        "dsl-match-spatial",
        """objects from lsst, ztf via alerce
inside (305.5822327501884, -18.7909207179724, 300.0arcsec)
match on position inside 1.0arcsec
""",
    ),
    FacadeScenario(
        "dsl-cross-provider",
        """objects from ztf via lasair
inside (124.87996115142856, -6.0205001, 5arcsec)
with lightcurve via fink
with lightcurve via lasair
order by summary.time.last_mjd desc
""",
        required_env=("LASAIR_ZTF_TOKEN",),
    ),
    FacadeScenario(
        "dsl-filter-candidate-flow",
        """objects from ztf via lasair
inside (124.87996115142856, -6.0205001, 300.0arcsec)
with lightcurve via fink
filter detection@ztf:fink.quality.real_bogus >= 0.8
with lightcurve via lasair
""",
        required_env=("LASAIR_ZTF_TOKEN",),
    ),
    FacadeScenario(
        "dsl-confirm-existence-quorum",
        """objects from ztf via alerce
inside (124.87996115142856, -6.0205001, 1.0arcsec)
latest 1
confirm by 2 via fink, alerce, antares
with lightcurve via fink
""",
    ),
    FacadeScenario(
        "dsl-confirm-predicate-quorum",
        """objects from ztf via alerce
inside (124.87996115142856, -6.0205001, 1.0arcsec)
latest 1
where exists classification.best.class
confirm by 2 via fink, lasair
with lightcurve via fink
""",
        required_env=("LASAIR_ZTF_TOKEN",),
    ),
    FacadeScenario(
        "dsl-classification-reuse",
        f"""objects from lsst via alerce
inside ({LSST_SAMPLE_RA}, {LSST_SAMPLE_DEC}, {LSST_SAMPLE_RADIUS_ARCSEC}arcsec)
where classification@{CLASSIFIER}.best.class = \"SN\" and classification@{CLASSIFIER}.best.probability >= 0.5
with classification from {CLASSIFIER}
""",
    ),
    FacadeScenario(
        "fink-lsst-consolidation",
        f"""objects from lsst via alerce
inside ({LSST_SAMPLE_RA}, {LSST_SAMPLE_DEC}, {LSST_SAMPLE_RADIUS_ARCSEC}arcsec)
where classification@{CLASSIFIER}.best.class = \"SN\" and classification@{CLASSIFIER}.best.probability >= 0.5
with classification from {CLASSIFIER}
with lightcurve via fink
order by summary.time.last_mjd desc
""",
    ),
)


_TRANSIENT_PATTERNS = (
    re.compile(r"HTTP Error (?:408|429|5\d\d)\b", re.IGNORECASE),
    re.compile(r"service unavailable|gateway timeout", re.IGNORECASE),
    re.compile(r"timed?\s*out|timeout(?:error)?", re.IGNORECASE),
    re.compile(r"connection (?:reset|refused|aborted|closed)", re.IGNORECASE),
    re.compile(r"temporary failure in name resolution|name or service not known", re.IGNORECASE),
    re.compile(r"network is unreachable|urlerror", re.IGNORECASE),
    re.compile(r"certificate.*expired|CERTIFICATE_VERIFY_FAILED", re.IGNORECASE),
)
_AUTH_PATTERNS = (
    re.compile(r"HTTP Error (?:401|403)\b", re.IGNORECASE),
    re.compile(r"unauthori[sz]ed|forbidden", re.IGNORECASE),
    re.compile(r"credential.*(?:missing|not found|required)", re.IGNORECASE),
)

_PROFILE_FUNCTIONS = (
    ("compile", "compile_surface"),
    ("plan", "plan_workflow"),
    ("bind", "bind_endpoint"),
    ("provider", "execute_bound_call"),
    ("normalize", "normalize_execution"),
    ("final_normalize", "normalize_workflow_execution"),
    ("local", "finalize_local_semantics"),
    ("staged", "execute_staged_workflow_run"),
)


def _exception_status(error: Exception) -> Status:
    text = f"{type(error).__name__}: {error}"
    if isinstance(error, ModuleNotFoundError) or any(p.search(text) for p in _AUTH_PATTERNS):
        return "SKIP"
    if any(p.search(text) for p in _TRANSIENT_PATTERNS):
        return "UNAVAILABLE"
    return "FAIL"


def _profile_summary(profiler: cProfile.Profile | None) -> str:
    """Return cumulative timings for existing execution-layer function boundaries.

    These values are intentionally diagnostic and non-additive: for example,
    ``staged`` contains provider and normalization work, while ``final_normalize``
    may contain calls to ``normalize_execution``. The point is attribution, not a
    synthetic accounting total.
    """

    if profiler is None:
        return ""
    stats = pstats.Stats(profiler)
    cumulative_by_name: dict[str, float] = {}
    for (_filename, _line, function_name), values in stats.stats.items():
        cumulative_by_name[function_name] = cumulative_by_name.get(function_name, 0.0) + values[3]
    return " profile[" + " ".join(
        f"{label}={cumulative_by_name.get(function_name, 0.0):.2f}s"
        for label, function_name in _PROFILE_FUNCTIONS
    ) + "]"


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    parser.add_argument(
        "--scenario",
        action="append",
        dest="scenarios",
        metavar="NAME",
        help="run only this facade scenario; repeatable",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="print the browser-safe JSON emitted by each successful execution",
    )
    parser.add_argument(
        "--profile-execute",
        action="store_true",
        help=(
            "profile execute_dsl and report cumulative compile/plan/bind/provider/"
            "normalization/local-semantic timings"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = _args()
    available = {scenario.name: scenario for scenario in SCENARIOS}

    if args.list:
        for scenario in SCENARIOS:
            print(scenario.name)
        return 0

    if args.scenarios:
        unknown = [name for name in args.scenarios if name not in available]
        if unknown:
            raise SystemExit("unknown scenario(s): " + ", ".join(unknown))
        selected = tuple(available[name] for name in args.scenarios)
    else:
        selected = SCENARIOS

    load_dotenv(REPO_ROOT / ".env", override=False)

    counts: dict[Status, int] = {
        status: 0 for status in ("PASS", "UNAVAILABLE", "SKIP", "FAIL")
    }
    print("=== ALERTISSIMO DSL FACADE LIVE ACCEPTANCE ===")
    print(f"Scenarios: {len(selected)}")
    print()

    for index, scenario in enumerate(selected, start=1):
        print(f"[{index:02d}/{len(selected):02d}] {scenario.name} ...", end="", flush=True)
        started = monotonic()
        validate_elapsed = 0.0
        execute_elapsed = 0.0
        json_elapsed = 0.0
        profiler: cProfile.Profile | None = None
        profile_detail = ""
        missing = [name for name in scenario.required_env if not os.environ.get(name)]
        if missing:
            status: Status = "SKIP"
            detail = "missing credential(s): " + ", ".join(missing)
        else:
            try:
                phase_started = monotonic()
                validation = validate_dsl(
                    scenario.source,
                    name=f"facade acceptance: {scenario.name}",
                )
                validate_elapsed = monotonic() - phase_started
                if not validation.is_runnable:
                    detail = (
                        f"DSL validation failed: parse={validation.parse_error!r} "
                        f"semantic={validation.semantic!r} "
                        f"lowering={validation.lowering_error!r}"
                    )
                    status = "FAIL"
                else:
                    profiler = cProfile.Profile() if args.profile_execute else None
                    phase_started = monotonic()
                    if profiler is not None:
                        profiler.enable()
                    try:
                        execution = execute_dsl(
                            scenario.source,
                            name=f"facade acceptance: {scenario.name}",
                        )
                    finally:
                        if profiler is not None:
                            profiler.disable()
                    execute_elapsed = monotonic() - phase_started
                    profile_detail = _profile_summary(profiler)

                    phase_started = monotonic()
                    json_text = execution.to_json()
                    json_elapsed = monotonic() - phase_started

                    payload = json.loads(json_text)
                    if payload.get("result_step_index") != execution.result_step_index:
                        raise RuntimeError(
                            "JSON result_step_index differs from facade result"
                        )
                    if len(payload.get("portfolios", ())) != len(execution.portfolios):
                        raise RuntimeError(
                            "JSON Portfolio count differs from facade result"
                        )
                    status = "PASS"
                    detail = (
                        f"validate={validate_elapsed:.2f}s "
                        f"execute={execute_elapsed:.2f}s "
                        f"json={json_elapsed:.2f}s "
                        f"steps={len(execution.result.steps)} "
                        f"result_step={execution.result_step_index} "
                        f"portfolios={len(execution.portfolios)} "
                        f"json_bytes={len(json_text.encode('utf-8'))}"
                        f"{profile_detail}"
                    )
                    if args.print_json:
                        print()
                        print(json_text)
            except Exception as error:
                if profiler is not None:
                    profiler.disable()
                    profile_detail = _profile_summary(profiler)
                if execute_elapsed == 0.0 and 'phase_started' in locals():
                    execute_elapsed = monotonic() - phase_started
                status = _exception_status(error)
                detail = (
                    f"validate={validate_elapsed:.2f}s "
                    f"execute={execute_elapsed:.2f}s "
                    f"json={json_elapsed:.2f}s "
                    f"{type(error).__name__}: {error}"
                    f"{profile_detail}"
                )

        elapsed = monotonic() - started
        counts[status] += 1
        print(f" {status} ({elapsed:.1f}s) {detail}")

    print()
    print("=== FACADE ACCEPTANCE SUMMARY ===")
    print(f"Passed:      {counts['PASS']}")
    print(f"Failures:    {counts['FAIL']}")
    print(f"Unavailable: {counts['UNAVAILABLE']}")
    print(f"Skipped:     {counts['SKIP']}")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
