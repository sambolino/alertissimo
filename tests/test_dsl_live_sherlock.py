"""Offline acceptance for the native Lasair ZTF Sherlock runner scenario."""
from contextlib import nullcontext
from copy import deepcopy
import json

import pytest

from alertissimo.api import execute_dsl
from alertissimo.data_layer.execution import RegistryEndpointExecutor, TransportResult
from scripts import live_dsl_discovery as runner

SCENARIO = "lasair-ztf-sherlock"
OID = "ZTF20aaaaaaa"
BOUNDS = ["--start", "2020-06-10T00:00:00Z", "--stop", "2020-06-20T00:00:00Z"]


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setattr(runner, "load_dotenv", lambda *a, **kw: None)
    monkeypatch.setattr(runner, "_revision", lambda: "fixture-revision")
    monkeypatch.setattr(runner, "_versions", lambda: {"python": "fixture"})
    monkeypatch.setattr(runner, "_deadline", lambda *_: nullcontext())
    monkeypatch.setenv("LASAIR_ZTF_TOKEN", "fixture-only")


class SherlockReplay:
    """Synthetic rows exercise orchestration; they are not new broker captures."""
    def __init__(self, empty=False):
        self.empty, self.calls = empty, []

    def execute(self, spec, params, headers=None):
        assert (spec.broker, spec.origin) == ("lasair", "ztf")
        self.calls.append((spec.endpoint, dict(params)))
        summary = {"objectId": OID, "ramean": 124.0, "decmean": -6.0,
                   "ncand": 8, "jdmin": 2459011.5, "jdmax": 2459018.5}
        context = {"classification": "AGN", "classificationReliability": 2,
                   "description": "Synthetic Sherlock context"}
        if spec.endpoint == "query":
            payload = [] if self.empty else [{**summary, **context}]
        elif spec.endpoint == "objects":
            assert params["objectIds"] == OID
            payload = [{"objectId": OID, "objectData": summary, "sherlock": context}]
        else:
            assert spec.endpoint == "lightcurves"
            assert params["objectIds"] == OID
            payload = [{"objectId": OID, "candidates": [
                {"candid": index, "jd": jd, "fid": 1, "ra": 124.0, "dec": -6.0,
                 "magpsf": 19.0, "sigmapsf": 0.1}
                for index, jd in ((501, 2459000.5), (502, 2459018.5))
            ]}]
        return TransportResult(deepcopy(payload), status_code=200, method="POST",
                               content_type="application/json")


def use_replay(monkeypatch, transport):
    executor = RegistryEndpointExecutor(transports={"rest": transport})
    monkeypatch.setattr(runner, "execute_dsl",
                        lambda source, **kwargs: execute_dsl(source, executor=executor, **kwargs))


def run_args(output):
    return ["--scenario", SCENARIO, *BOUNDS, "--latest", "1", "--output-dir", str(output)]


@pytest.mark.parametrize("mode", ["detection", "first", "last"])
def test_validation_records_the_native_scenarios_actual_last_mode(isolated, monkeypatch, tmp_path, mode):
    def forbidden(*args, **kwargs):
        pytest.fail("validation attempted provider execution")
    monkeypatch.setattr(runner, "execute_dsl", forbidden)
    assert runner.main(["--validate-only", "--scenario", SCENARIO, "--time-mode", mode,
                        "--output-dir", str(tmp_path)]) == 0
    source = (tmp_path / SCENARIO / "00.dsl").read_text()
    summary = json.loads((tmp_path / SCENARIO / "summary.json").read_text())
    assert "last within 1h" in source and "inside (" not in source
    assert 'classification@sherlock:lasair.best.class = "AGN"' in source
    assert summary["resolved_bounds"]["mode"] == "last"


def test_native_runner_saves_join_assertions_and_full_survivor_history(isolated, monkeypatch, tmp_path):
    transport = SherlockReplay()
    use_replay(monkeypatch, transport)
    assert runner.main(run_args(tmp_path)) == 0
    summary = json.loads((tmp_path / SCENARIO / "summary.json").read_text())
    assert summary["status"] == "PASS"
    assert summary["resolved_bounds"]["mode"] == "last"
    item, = summary["programs"]
    assert item["candidate_identities"] == [["ztf", OID]]
    query, = [params for endpoint, params in transport.calls if endpoint == "query"]
    assert query["tables"] == "objects,sherlock_classifications"
    assert 'sherlock_classifications.classification = "AGN"' in query["conditions"]
    assert query["conditions"].endswith("ORDER BY objects.objectId")
    exported = json.loads((tmp_path / SCENARIO / "00.result.json").read_text())
    portfolio, = exported["portfolios"]
    measurements = [r for r in portfolio["records"] if r["semantic_type"] == "measurement@ztf:lasair"]
    assert {r["fields"]["time.mjd"] for r in measurements} == {59000.0, 59018.0}
    classes = [r for r in portfolio["records"] if r["semantic_type"] == "classification@sherlock:lasair"]
    assert classes and all(r["fields"]["best.class"] == "AGN" for r in classes)
    assert all(r["fields"]["best.score"] == 2 and "best.probability" not in r["fields"] for r in classes)


@pytest.mark.parametrize("strict,code", [(False, 0), (True, 2)])
def test_empty_native_population_is_not_a_nonempty_acceptance(isolated, monkeypatch, tmp_path, strict, code):
    transport = SherlockReplay(empty=True)
    use_replay(monkeypatch, transport)
    assert runner.main(run_args(tmp_path) + (["--require-all-pass"] if strict else [])) == code
    summary = json.loads((tmp_path / SCENARIO / "summary.json").read_text())
    assert summary["status"] == "SKIP"
    assert [endpoint for endpoint, _ in transport.calls] == ["query"]


@pytest.mark.parametrize("change", ["tables", "selector", "broker"])
def test_nonempty_result_without_native_route_proof_fails(isolated, monkeypatch, tmp_path, change):
    use_replay(monkeypatch, SherlockReplay())
    original = runner._execution_evidence
    def altered(result):
        evidence = original(result)
        for item in evidence:
            if item["step_index"] == 0 and item["endpoint"] == "query":
                if change == "tables":
                    item["params"]["tables"] = "objects"
                elif change == "selector":
                    item["params"]["conditions"] = "1=1 ORDER BY objects.objectId"
                else:
                    item["broker"] = "fink"
        return evidence
    monkeypatch.setattr(runner, "_execution_evidence", altered)
    assert runner.main(run_args(tmp_path)) == 1
    summary = json.loads((tmp_path / SCENARIO / "summary.json").read_text())
    assert summary["status"] == "FAIL"
    assert "native Sherlock discovery join/selector" in summary["detail"]
