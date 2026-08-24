#!/usr/bin/env python3
"""Run the current Alertissimo acceptance surface and report every outcome.

This is intentionally a *scenario runner*, not one giant WorkflowIR.  Each
scenario runs independently so one provider outage does not hide failures in
other providers or orchestration paths.

Default usage from the repository root::

    PYTHONPATH=. python scripts/live_acceptance.py

Useful options::

    PYTHONPATH=. python scripts/live_acceptance.py --list
    PYTHONPATH=. python scripts/live_acceptance.py --scenario multisurvey-discovery
    PYTHONPATH=. python scripts/live_acceptance.py --scenario dsl-filter-candidate-flow --verbose

Statuses:
- PASS:          acceptance path completed and its invariants passed
- INCONCLUSIVE:  live data did not exercise the intended branch (exit code 3)
- UNAVAILABLE:   provider/network transient such as HTTP 5xx or timeout
- SKIP:          missing credential or authentication/access problem
- FAIL:          architecture, planning, binding, execution-contract,
                 normalization, derivation, presentation, or invariant failure

The process exits nonzero only when at least one scenario is FAIL.  Provider
availability is therefore visible without turning this diagnostic sweep into a
network-uptime gate.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Callable, Literal

from dotenv import load_dotenv


Status = Literal["PASS", "INCONCLUSIVE", "UNAVAILABLE", "SKIP", "FAIL"]


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    command: Callable[[Path], tuple[str, ...]]
    required_env: tuple[str, ...] = ()
    live: bool = True


@dataclass(frozen=True)
class ScenarioResult:
    scenario: Scenario
    status: Status
    detail: str
    returncode: int | None
    log_path: Path
    elapsed_seconds: float


REPO_ROOT = Path(__file__).resolve().parents[1]


def _python_script(path: str, *args: str) -> Callable[[Path], tuple[str, ...]]:
    return lambda _logs: (sys.executable, str(REPO_ROOT / path), *args)


def _python_module(module: str, *args: str) -> Callable[[Path], tuple[str, ...]]:
    return lambda _logs: (sys.executable, "-m", module, *args)


def _portfolio_command(origin: str, object_id: str) -> Callable[[Path], tuple[str, ...]]:
    def command(log_dir: Path) -> tuple[str, ...]:
        output = log_dir / f"portfolio-{origin}.html"
        return (
            sys.executable,
            str(REPO_ROOT / "scripts/live_portfolio_html.py"),
            "--origin",
            origin,
            "--object-id",
            object_id,
            "--output",
            str(output),
            "--no-open",
        )

    return command


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "multisurvey-discovery",
        "DSL cone search -> ALeRCE LSST + ZTF -> origin-preserving Portfolios",
        _python_script("scripts/live_dsl_multisurvey.py"),
    ),
    Scenario(
        "dsl-match-spatial",
        "DSL ALeRCE LSST+ZTF discovery -> normalized local positional MatchStep adjacency",
        _python_script("scripts/live_dsl_match.py"),
    ),
    Scenario(
        "dsl-cross-provider",
        "DSL Lasair/ZTF search -> late-bound Fink/ZTF + Lasair/ZTF retrieval",
        _python_script("scripts/live_dsl_complex.py"),
        required_env=("LASAIR_ZTF_TOKEN",),
    ),
    Scenario(
        "dsl-filter-candidate-flow",
        "DSL Search -> Fink evidence -> local Filter -> survivor-bound Lasair Get",
        _python_script("scripts/live_dsl_filter.py"),
        required_env=("LASAIR_ZTF_TOKEN",),
    ),
    Scenario(
        "dsl-incremental-continuation",
        "public facade first pass -> continued Filter -> survivor-bound Lasair Get",
        _python_script("scripts/live_dsl_continuation.py"),
        required_env=("LASAIR_ZTF_TOKEN",),
    ),
    Scenario(
        "dsl-confirm-existence-quorum",
        "DSL ALeRCE discovery -> 2-of-3 Fink/ALeRCE/ANTARES Confirm -> survivor-bound Fink Get",
        _python_script("scripts/live_dsl_confirm.py"),
    ),
    Scenario(
        "dsl-confirm-predicate-quorum",
        "DSL ALeRCE where exists classification.best.class -> 2-of-2 Fink/Lasair Confirm -> survivor-bound Fink Get",
        _python_script("scripts/live_dsl_confirm_predicate.py"),
        required_env=("LASAIR_ZTF_TOKEN",),
    ),
    Scenario(
        "dsl-classification-reuse",
        "literal DSL ALeRCE/LSST classifier search -> semantic execution reuse",
        _python_module("scripts.smoke", "dsl-pipeline", "--live"),
    ),
    Scenario(
        "explicit-multi-provider",
        "programmatic IR -> Fink + Lasair + ALeRCE ZTF retrieval",
        _python_module("scripts.smoke", "multi-provider", "--live"),
        required_env=("LASAIR_ZTF_TOKEN",),
    ),
    Scenario(
        "explicit-multi-target",
        "programmatic IR -> collection binding through Fink and Lasair ZTF",
        _python_module("scripts.smoke", "multi-target", "--live"),
        required_env=("LASAIR_ZTF_TOKEN",),
    ),
    Scenario(
        "color-magnitude-derivation",
        "Fink/ZTF retrieval -> normalized Portfolio -> local color-magnitude derivation",
        _python_module("scripts.smoke", "color-magnitude", "--live"),
    ),
    Scenario(
        "alerce-lsst-lightcurve",
        "programmatic IR -> ALeRCE/LSST plan/bind/execute/normalize",
        _python_script("scripts/live_smoke_alerce.py"),
    ),
    Scenario(
        "antares-ztf-lsst-lookups",
        "ANTARES ZTF + LSST authoritative lookups -> semantic normalization",
        _python_script("scripts/live_smoke_antares.py"),
    ),
    Scenario(
        "crossmatch-retrieval",
        "GetCrossmatchStep -> ANTARES/ZTF target binding -> live Gaia crossmatch normalization",
        _python_script("scripts/live_crossmatch.py"),
    ),
    Scenario(
        "lasair-ztf-portfolio-html",
        "Lasair/ZTF object -> Portfolio -> edges -> HTML presentation",
        _portfolio_command("ztf", "ZTF20acpwljl"),
        required_env=("LASAIR_ZTF_TOKEN",),
    ),
    Scenario(
        "lasair-lsst-portfolio-html",
        "Lasair/LSST object -> Portfolio -> edges -> HTML presentation",
        _portfolio_command("lsst", "313761042336317573"),
        required_env=("LASAIR_LSST_TOKEN",),
    ),
    Scenario(
        "fink-lsst-consolidation",
        "ALeRCE LSST search/reuse -> Fink sources+fp -> semantic Step consolidation",
        _python_script("scripts/live_dsl_fink_lsst.py"),
    ),
    Scenario(
        "partial-failure-control",
        "fixture control: fail-fast state preserves prior/in-step successes",
        _python_module("scripts.smoke", "partial-failure"),
        live=False,
    ),
)


_TRANSIENT_PATTERNS = (
    re.compile(r"HTTP Error (?:408|429|5\d\d)\b", re.IGNORECASE),
    re.compile(r"\b(?:502|503|504)\b.*(?:gateway|service|timeout|time-out)", re.IGNORECASE),
    re.compile(r"gateway (?:timeout|time-out)", re.IGNORECASE),
    re.compile(r"service unavailable", re.IGNORECASE),
    re.compile(r"timed?\s*out|timeout(?:error)?", re.IGNORECASE),
    re.compile(r"connection (?:reset|refused|aborted|closed)", re.IGNORECASE),
    re.compile(r"remote end closed connection", re.IGNORECASE),
    re.compile(r"temporary failure in name resolution|name or service not known", re.IGNORECASE),
    re.compile(r"network is unreachable", re.IGNORECASE),
    re.compile(r"urlerror", re.IGNORECASE),
)

_AUTH_PATTERNS = (
    re.compile(r"HTTP Error (?:401|403)\b", re.IGNORECASE),
    re.compile(r"\b(?:401|403)\b.*(?:unauthori[sz]ed|forbidden)", re.IGNORECASE),
    re.compile(r"unauthori[sz]ed|forbidden", re.IGNORECASE),
    re.compile(r"credential.*(?:missing|not found|required)", re.IGNORECASE),
)


def _first_matching_line(text: str, patterns: tuple[re.Pattern[str], ...]) -> str | None:
    for line in reversed(text.splitlines()):
        if any(pattern.search(line) for pattern in patterns):
            return line.strip()[:240]
    return None


def _last_meaningful_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1][:240] if lines else "no diagnostic output"


def _classify(returncode: int, output: str) -> tuple[Status, str]:
    if returncode == 0:
        return "PASS", _last_meaningful_line(output)
    if returncode == 3:
        return "INCONCLUSIVE", _last_meaningful_line(output)

    auth = _first_matching_line(output, _AUTH_PATTERNS)
    if auth is not None:
        return "SKIP", auth

    transient = _first_matching_line(output, _TRANSIENT_PATTERNS)
    if transient is not None:
        return "UNAVAILABLE", transient

    return "FAIL", _last_meaningful_line(output)


def _run_scenario(
    scenario: Scenario,
    *,
    log_dir: Path,
    timeout_seconds: float,
    verbose: bool,
) -> ScenarioResult:
    missing = tuple(name for name in scenario.required_env if not os.environ.get(name))
    log_path = log_dir / f"{scenario.name}.log"

    if missing:
        detail = "missing credential(s): " + ", ".join(missing)
        log_path.write_text(detail + "\n", encoding="utf-8")
        return ScenarioResult(scenario, "SKIP", detail, None, log_path, 0.0)

    command = scenario.command(log_dir)
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(REPO_ROOT)
        if not existing_pythonpath
        else str(REPO_ROOT) + os.pathsep + existing_pythonpath
    )

    import time

    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_seconds,
            check=False,
        )
        elapsed = time.monotonic() - started
        output = completed.stdout or ""
        log_path.write_text(output, encoding="utf-8")
        status, detail = _classify(completed.returncode, output)
        result = ScenarioResult(
            scenario,
            status,
            detail,
            completed.returncode,
            log_path,
            elapsed,
        )
    except subprocess.TimeoutExpired as error:
        elapsed = time.monotonic() - started
        captured = error.stdout or ""
        if isinstance(captured, bytes):
            captured = captured.decode("utf-8", errors="replace")
        detail = f"scenario exceeded {timeout_seconds:g}s timeout"
        output = captured + ("\n" if captured else "") + detail + "\n"
        log_path.write_text(output, encoding="utf-8")
        status: Status = "UNAVAILABLE" if scenario.live else "FAIL"
        result = ScenarioResult(scenario, status, detail, None, log_path, elapsed)

    if verbose:
        print(f"\n--- {scenario.name} output ({result.log_path}) ---")
        print(result.log_path.read_text(encoding="utf-8", errors="replace").rstrip())
        print(f"--- end {scenario.name} ---\n")

    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list scenario names")
    parser.add_argument(
        "--scenario",
        action="append",
        dest="scenarios",
        metavar="NAME",
        help="run only this scenario (repeatable)",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=180.0,
        help="per-scenario timeout; default: 180",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        help="directory for per-scenario logs and generated HTML",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print each scenario's complete captured output",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    available = {scenario.name: scenario for scenario in SCENARIOS}

    if args.list:
        if args.scenarios or args.log_dir or args.verbose:
            _parser().error("--list cannot be combined with run options")
        for scenario in SCENARIOS:
            mode = "live" if scenario.live else "offline-control"
            print(f"{scenario.name:30} [{mode}] {scenario.description}")
        return 0

    if args.timeout_seconds <= 0:
        _parser().error("--timeout-seconds must be positive")

    if args.scenarios:
        unknown = [name for name in args.scenarios if name not in available]
        if unknown:
            _parser().error("unknown scenario(s): " + ", ".join(unknown))
        selected = tuple(available[name] for name in args.scenarios)
    else:
        selected = SCENARIOS

    load_dotenv(REPO_ROOT / ".env", override=False)

    if args.log_dir is None:
        log_dir = Path(tempfile.mkdtemp(prefix="alertissimo-live-acceptance-"))
    else:
        log_dir = args.log_dir.resolve()
        log_dir.mkdir(parents=True, exist_ok=True)

    metadata = (
        f"started_utc={datetime.now(timezone.utc).isoformat()}\n"
        f"python={sys.executable}\n"
        f"repo={REPO_ROOT}\n"
        f"scenarios={','.join(s.name for s in selected)}\n"
    )
    (log_dir / "run.txt").write_text(metadata, encoding="utf-8")

    print("=== ALERTISSIMO LIVE ACCEPTANCE ===")
    print(f"Scenarios: {len(selected)}")
    print(f"Logs:      {log_dir}")
    print()

    results: list[ScenarioResult] = []
    for index, scenario in enumerate(selected, start=1):
        print(f"[{index:02d}/{len(selected):02d}] {scenario.name} ...", end="", flush=True)
        result = _run_scenario(
            scenario,
            log_dir=log_dir,
            timeout_seconds=args.timeout_seconds,
            verbose=args.verbose,
        )
        results.append(result)
        print(f" {result.status} ({result.elapsed_seconds:.1f}s)")
        if result.status != "PASS":
            print(f"         {result.detail}")

    print()
    print("=== LIVE ACCEPTANCE SUMMARY ===")
    width = max(len(result.scenario.name) for result in results)
    for result in results:
        print(
            f"{result.status:13} {result.scenario.name:<{width}}  "
            f"{result.elapsed_seconds:6.1f}s  {result.detail}"
        )

    counts = {
        status: sum(result.status == status for result in results)
        for status in ("PASS", "FAIL", "UNAVAILABLE", "INCONCLUSIVE", "SKIP")
    }
    print()
    print(f"Passed:                 {counts['PASS']}")
    print(f"Architectural failures: {counts['FAIL']}")
    print(f"Unavailable:            {counts['UNAVAILABLE']}")
    print(f"Inconclusive:           {counts['INCONCLUSIVE']}")
    print(f"Skipped:                {counts['SKIP']}")
    print(f"Logs:                   {log_dir}")

    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
