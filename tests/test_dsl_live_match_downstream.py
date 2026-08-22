"""Keep the live Match -> Get acceptance helper wired to the real planner."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from scripts.live_dsl_match_downstream import _HybridLiveExecutor


ROOT = Path(__file__).resolve().parents[1]


class _NeverDelegate:
    def execute(self, *args, **kwargs):
        raise AssertionError("known-offline Fink/LSST call was delegated to real transport")


def test_live_match_downstream_plan_only_uses_match_as_candidate_owner():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/live_dsl_match_downstream.py",
            "--plan-only",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Step 0: op=cone_search" in completed.stdout
    assert "Step 1: op=match" in completed.stdout
    assert "Step 2: op=get_lightcurve" in completed.stdout
    assert (
        "fink/lsst/sources candidate_input_from=CandidateInputRef(step_index=1) required"
        in completed.stdout
    )
    assert (
        "fink/lsst/fp candidate_input_from=CandidateInputRef(step_index=1) supplementary"
        in completed.stdout
    )
    assert (
        "fink/ztf/objects candidate_input_from=CandidateInputRef(step_index=1) required"
        in completed.stdout
    )
    assert "OK: every downstream Fink plan depends on MatchStep, not Search" in completed.stdout
    assert "NOTE: Fink/LSST is known offline; its bound calls will be checked but not sent" in completed.stdout
    assert "Plan-only mode: no provider APIs contacted." in completed.stdout


def test_live_match_downstream_skips_known_offline_fink_lsst_transport():
    executor = _HybridLiveExecutor(_NeverDelegate(), live_fink_lsst=False)
    result = executor.execute(
        "fink",
        "lsst",
        "sources",
        params={"diaObjectId": "313936986529333309"},
    )

    assert result.payload == []
    assert result.execution_provenance.broker == "fink"
    assert result.execution_provenance.origin == "lsst"
    assert result.execution_provenance.endpoint == "sources"
    assert result.execution_provenance.params["diaObjectId"] == "313936986529333309"
    assert result.execution_provenance.status == "skipped-known-offline"
    assert executor.skipped_fink_lsst == [
        ("sources", {"diaObjectId": "313936986529333309"})
    ]
