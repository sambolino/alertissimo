"""Offline CLI contracts for the live discovery runner; never contact providers."""

from contextlib import nullcontext
from copy import deepcopy
import json
from urllib.error import HTTPError, URLError

import pytest

from alertissimo.api import execute_dsl
from alertissimo.data_layer.execution import MissingEndpointCredentialError, RegistryEndpointExecutor, TransportResult
from scripts import live_dsl_discovery as runner


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setattr(runner, "load_dotenv", lambda *a, **kw: None)
    monkeypatch.setattr(runner, "_revision", lambda: "fixture-revision")
    monkeypatch.setattr(runner, "_versions", lambda: {"python": "fixture"})
    monkeypatch.setattr(runner, "_deadline", lambda *_: nullcontext())


def forbidden(*args, **kwargs):
    raise AssertionError("provider execution was attempted")


class FinkReplay:
    def __init__(self, *, empty=False):
        self.empty = empty
        self.calls = []

    def execute(self, spec, params, headers=None):
        assert (spec.broker, spec.origin) == ("fink", "ztf")
        self.calls.append((spec.endpoint, dict(params)))
        ids = (runner.OBJECT_ID, runner.SECOND_ID)
        if spec.endpoint == "objects":
            ids = params["objectId"].split(",")
        else:
            assert spec.endpoint == "latests"
        rows = [] if self.empty else [
            {"i:objectId": oid, "i:candid": (runner.OBJECT_ID, runner.SECOND_ID).index(oid) + 1,
             "i:fid": 1, "i:jd": 2459397.0, "i:magpsf": 19.0,
             "i:ra": 124.0, "i:dec": -6.0, "i:drb": 0.95,
             "v:classification": "SN candidate"}
            for oid in ids
        ]
        return TransportResult(deepcopy(rows), status_code=200, content_type="application/json")


def use_replay(monkeypatch, transport):
    executor = RegistryEndpointExecutor(transports={"rest": transport})

    def replay(source, **kwargs):
        return execute_dsl(source, executor=executor, **kwargs)

    monkeypatch.setattr(runner, "execute_dsl", replay)


def test_list_does_not_validate_execute_load_credentials_or_create_output(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(runner, "execute_dsl", forbidden)
    monkeypatch.setattr(runner, "validate_dsl", forbidden)
    monkeypatch.setattr(runner, "load_dotenv", forbidden)
    output = tmp_path / "not-created"
    assert runner.main(["--list", "--output-dir", str(output)]) == 0
    text = capsys.readouterr().out
    assert all(name in text for name in runner.SCENARIOS)
    assert not output.exists()


def test_validate_only_plans_every_scenario_without_execution(isolated, monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "execute_dsl", forbidden)
    output = tmp_path / "validation"
    assert runner.main(["--validate-only", "--output-dir", str(output)]) == 0
    manifest = json.loads((output / "run.json").read_text())
    assert manifest["revision"] == "fixture-revision"
    assert {r["scenario"] for r in manifest["results"]} == set(runner.SCENARIOS)
    assert all(r["status"] == "PASS" and r["phase"] == "validation" for r in manifest["results"])
    assert not list(output.rglob("*.result.json"))
    assert len(list(output.rglob("*.dsl"))) == len(runner.SCENARIOS) + 1


def test_fixed_bounds_are_normalized_to_utc_and_saved_with_source(isolated, monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "execute_dsl", forbidden)
    output = tmp_path / "fixed"
    assert runner.main(["--validate-only", "--scenario", "fink-class-time",
                        "--start", "2021-07-01T02:00:00+02:00", "--stop", "2021-07-02T02:00:00+02:00",
                        "--output-dir", str(output)]) == 0
    summary = json.loads((output / "fink-class-time/summary.json").read_text())
    assert summary["resolved_bounds"] == {"start": "2021-07-01T00:00:00+00:00",
                                           "stop": "2021-07-02T00:00:00+00:00",
                                           "mode": "detection", "fixed_override": True}
    assert 'within ["2021-07-01T00:00:00+00:00", "2021-07-02T00:00:00+00:00"]' in (output / "fink-class-time/00.dsl").read_text()


@pytest.mark.parametrize("mode", ["first", "last"])
def test_time_mode_builds_runnable_scoped_programs(isolated, monkeypatch, tmp_path, mode):
    monkeypatch.setattr(runner, "execute_dsl", forbidden)
    output = tmp_path / mode
    args = ["--validate-only", "--time-mode", mode, "--output-dir", str(output)]
    for name in sorted(runner.TIME_SCENARIOS):
        args += ["--scenario", name]
    assert runner.main(args) == 0
    for name in runner.TIME_SCENARIOS:
        assert f"{mode} within 1h" in (output / name / "00.dsl").read_text()
        assert json.loads((output / name / "summary.json").read_text())["status"] == "PASS"


@pytest.mark.parametrize("options", [
    ["--start", "2021-07-01T00:00:00Z"],
    ["--start", "2021-07-02T00:00:00Z", "--stop", "2021-07-01T00:00:00Z"],
    ["--start", "2021-07-01", "--stop", "2021-07-02"],
    ["--window-hours", "0"], ["--latest", "0"], ["--timeout-seconds", "nan"],
    ["--ra", "nan"], ["--radius-arcsec", "-1"],
])
def test_invalid_options_fail_before_any_facade_call(monkeypatch, options):
    monkeypatch.setattr(runner, "execute_dsl", forbidden)
    monkeypatch.setattr(runner, "validate_dsl", forbidden)
    monkeypatch.setattr(runner, "load_dotenv", forbidden)
    with pytest.raises(SystemExit) as error:
        runner.main(options)
    assert error.value.code == 2


def test_existing_evidence_is_not_overwritten(isolated, monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "validate_dsl", forbidden)
    marker = tmp_path / "keep.json"
    marker.write_text("original evidence")
    with pytest.raises(SystemExit) as error:
        runner.main(["--validate-only", "--output-dir", str(tmp_path)])
    assert error.value.code == 2
    assert marker.read_text() == "original evidence"
    assert list(tmp_path.iterdir()) == [marker]


@pytest.mark.parametrize("error,status", [
    (HTTPError("https://example.invalid", 504, "Gateway Timeout", {}, None), "UNAVAILABLE"),
    (HTTPError("https://example.invalid", 401, "Unauthorized", {}, None), "SKIP"),
    (HTTPError("https://example.invalid", 400, "Bad request", {}, None), "FAIL"),
    (URLError("connection refused"), "UNAVAILABLE"), (TimeoutError("deadline"), "UNAVAILABLE"),
    (type("ConnectionError", (Exception,), {"__module__": "requests.exceptions"})("connection reset"), "UNAVAILABLE"),
    (MissingEndpointCredentialError("missing required credential"), "SKIP"),
    (RuntimeError("incomplete result n=100"), "FAIL"),
    (RuntimeError("invalid temporal evidence"), "FAIL"),
])
def test_failure_classification_keeps_contract_failures_separate(error, status):
    try:
        raise RuntimeError("step execution failed") from error
    except RuntimeError as wrapped:
        assert runner.classify_error(wrapped) == status


def test_success_saves_final_candidates_physical_provenance_and_counts(isolated, monkeypatch, tmp_path):
    use_replay(monkeypatch, FinkReplay())
    output = tmp_path / "live-replay"
    assert runner.main(["--scenario", "multi-object-consumer", "--output-dir", str(output)]) == 0
    summary = json.loads((output / "multi-object-consumer/summary.json").read_text())
    assert summary["status"] == "PASS" and summary["phase"] == "live"
    item, = summary["programs"]
    assert item["candidate_identities"] == [["ztf", runner.SECOND_ID], ["ztf", runner.OBJECT_ID]]
    assert item["candidate_count"] == 2 and item["unique_physical_executions"] >= 1
    assert all(e["broker"] == "fink" and e["endpoint"] == "objects" for e in item["executions"])
    exported = json.loads((output / "multi-object-consumer/00.result.json").read_text())
    assert len(exported["portfolios"]) == 2
    assert all(p["executions"] for p in exported["portfolios"])


@pytest.mark.parametrize("strict,expected_code", [(False, 0), (True, 2)])
def test_empty_live_population_is_unexercised_and_still_keeps_execution_metadata(isolated, monkeypatch, tmp_path, strict, expected_code):
    transport = FinkReplay(empty=True)
    use_replay(monkeypatch, transport)
    output = tmp_path / "empty"
    options = ["--require-all-pass"] if strict else []
    assert runner.main(["--scenario", "fink-class-time", "--output-dir", str(output), *options]) == expected_code
    summary = json.loads((output / "fink-class-time/summary.json").read_text())
    assert summary["status"] == "SKIP" and "empty" in summary["detail"]
    item, = summary["programs"]
    assert item["candidate_count"] == 0 and item["executions"][0]["endpoint"] == "latests"
    assert (output / "fink-class-time/00.result.json").is_file()
    assert [name for name, _ in transport.calls] == ["latests"]


def test_assertion_failure_retains_result_and_next_scenario_runs(isolated, monkeypatch, tmp_path):
    use_replay(monkeypatch, FinkReplay())
    original = runner._assert_result

    def check(name, *args):
        if name == "fink-class-time":
            raise RuntimeError("controlled invariant failure")
        return original(name, *args)

    monkeypatch.setattr(runner, "_assert_result", check)
    output = tmp_path / "failure"
    assert runner.main(["--scenario", "fink-class-time", "--scenario", "multi-object-consumer",
                        "--start", "2021-07-01T00:00:00Z", "--stop", "2021-07-02T00:00:00Z",
                        "--output-dir", str(output)]) == 1
    manifest = json.loads((output / "run.json").read_text())
    assert [r["status"] for r in manifest["results"]] == ["FAIL", "PASS"]
    assert (output / "fink-class-time/00.result.json").is_file()
    assert "controlled invariant failure" in (output / "fink-class-time/error.log").read_text()


def test_credentials_are_not_written_in_failure_logs(isolated, monkeypatch, tmp_path):
    monkeypatch.setenv("LASAIR_ZTF_TOKEN", "fixture-secret-do-not-save")

    def failed(*args, **kwargs):
        raise RuntimeError("provider rejected fixture-secret-do-not-save")

    monkeypatch.setattr(runner, "execute_dsl", failed)
    output = tmp_path / "redacted"
    assert runner.main(["--scenario", "multi-object-consumer", "--output-dir", str(output)]) == 1
    for path in output.rglob("*"):
        if path.is_file():
            assert "fixture-secret-do-not-save" not in path.read_text()
    assert "<redacted>" in (output / "multi-object-consumer/error.log").read_text()


def test_live_deadline_restores_signal_handler_after_exception(monkeypatch):
    # Use the real context manager but fake its OS calls; no timer is started.
    events = []
    previous = object()
    monkeypatch.setattr(runner.signal, "signal", lambda *args: events.append(("handler", args)) or previous)
    monkeypatch.setattr(runner.signal, "setitimer", lambda *args: events.append(("timer", args)))
    with pytest.raises(RuntimeError, match="controlled"):
        with runner._deadline(5):
            raise RuntimeError("controlled")
    assert events[-2] == ("timer", (runner.signal.ITIMER_REAL, 0))
    assert events[-1] == ("handler", (runner.signal.SIGALRM, previous))
