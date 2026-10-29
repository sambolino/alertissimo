"""Lasair ZTF temporal recipes with SQLite discovery and synthetic mixed history.

No broker requests. Synthetic histories make gaps, upper limits and response
coverage observable. A separate native-summary case uses unchanged capture data.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sqlite3

import pytest
import yaml

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import EndpointRegistry, ExecutionPolicy, RegistryEndpointExecutor, TransportResult
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.runtime.capability_graph import CapabilityGraphError, build_capability_graph
from alertissimo.orchestration.normalization import TimeSelectionError, normalize_workflow_execution, summary_object_identity
from alertissimo.orchestration.runtime import WorkflowExecutionError


NOW = datetime(2020, 6, 20, tzinfo=timezone.utc)  # UTC MJD 59020
IDS = tuple(f"ZTF20{letter * 7}" for letter in "abcdef")
ROWS = [
    {"objectId": IDS[0], "ramean": 120.0, "decmean": -6.0, "ncand": 7, "jdmin": 2459000.5, "jdmax": 2459030.5},
    {"objectId": IDS[1], "ramean": 120.0, "decmean": -6.0, "ncand": 8, "jdmin": 2459000.5, "jdmax": 2459090.5},
    {"objectId": IDS[2], "ramean": 120.0, "decmean": -6.0, "ncand": 3, "jdmin": 2459011.5, "jdmax": 2459050.5},
    {"objectId": IDS[3], "ramean": 120.0, "decmean": -6.0, "ncand": 10, "jdmin": 2458990.5, "jdmax": 2459015.5},
]
HISTORY = {IDS[0]: [59000, 59012, 59030], IDS[1]: [59000, 59090],
           IDS[2]: [59011, 59050], IDS[3]: [58990, 59015]}


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


class SmallPageRegistry(EndpointRegistry):
    def __init__(self, page_size=2):
        super().__init__()
        self.page_size = page_size

    def resolve(self, broker, origin, endpoint):
        spec = super().resolve(broker, origin, endpoint)
        if (broker, origin, endpoint) == ("lasair", "ztf", "query"):
            return replace(spec, params={**spec.params, "limit": {**spec.params["limit"], "default": self.page_size}})
        return spec


class ReplayTransport:
    name = "fixture"

    def __init__(self, *, rows=None, histories=None, failure=None, ignore_sql=False):
        self.rows = deepcopy(ROWS if rows is None else rows)
        self.histories = deepcopy(HISTORY if histories is None else histories)
        self.failure, self.ignore_sql = failure, ignore_sql
        self.calls = []

    def execute(self, spec, params, headers=None):
        assert (spec.broker, spec.origin, spec.method, spec.request_encoding) == ("lasair", "ztf", "POST", "form")
        assert headers["Authorization"] == "Token fixture-only"
        self.calls.append((spec.endpoint, dict(params)))
        if spec.endpoint == "cone":
            assert params["requestType"] == "all"
            payload = {"error": "bad cone"} if self.failure == "cone_error" else [
                {"object": row["objectId"], "separation": 1.0} for row in self.rows]
        elif spec.endpoint == "query":
            if self.failure == "query_error":
                return TransportResult({"error": "controlled summary error"}, status_code=200)
            with sqlite3.connect(":memory:") as db:
                db.row_factory = sqlite3.Row
                db.execute("CREATE TABLE objects(objectId TEXT PRIMARY KEY, ramean REAL, decmean REAL, ncand INTEGER, jdmin REAL, jdmax REAL)")
                db.executemany("INSERT INTO objects VALUES (:objectId,:ramean,:decmean,:ncand,:jdmin,:jdmax)", self.rows)
                condition = "1=1 ORDER BY objects.objectId" if self.ignore_sql else params["conditions"]
                sql = f"SELECT {params['selected']} FROM {params['tables']} WHERE {condition} LIMIT ? OFFSET ?"
                payload = [dict(row) for row in db.execute(sql, (params["limit"], params["offset"]))]
            if self.failure == "missing_summary":
                payload = [row for row in payload if row["objectId"] != IDS[3]]
        else:
            assert spec.endpoint == "lightcurves"
            if self.failure == "history_request":
                raise RuntimeError("history unavailable")
            payload = []
            for oid in params["objectIds"].split(","):
                points = [{"candid": i + 1, "jd": mjd + 2400000.5, "fid": 1,
                           "magpsf": 20.0, "sigmapsf": 0.1} for i, mjd in enumerate(self.histories[oid])]
                # Upper limits and forced photometry inside the window must not
                # rescue the gap candidate. Retain them in the raw response.
                points.append({"jd": 2459012.5, "fid": 1, "diffmaglim": 22.0})
                payload.append({"objectId": oid, "candidates": points,
                                "forcedphot": [{"jd": 2459012.5, "forcediffimflux": 123.0}]})
            if self.failure == "omitted":
                payload = payload[:-1]
            elif self.failure == "empty_batch":
                payload = []
            elif self.failure == "duplicate":
                payload.append(deepcopy(payload[0]))
            elif self.failure == "foreign":
                payload[0]["objectId"] = IDS[5]
            elif self.failure == "object_error":
                payload[0] = {"error": "controlled object error"}
            elif self.failure == "missing_branch":
                payload[0].pop("candidates")
            elif self.failure == "null_branch":
                payload[0]["candidates"] = None
            elif self.failure == "unknown_row":
                payload[0]["candidates"] = [{"jd": 2459012.5, "fid": 1}]
            elif self.failure == "empty_history":
                for row in payload:
                    row["candidates"] = []
        return TransportResult(payload, method="POST", status_code=200, content_type="application/json")


def replay(monkeypatch, *, max_pages=8, page_size=2, **kwargs):
    monkeypatch.setenv("LASAIR_ZTF_TOKEN", "fixture-only")
    transport, registry = ReplayTransport(**kwargs), SmallPageRegistry(page_size)
    executor = RegistryEndpointExecutor(registry, transports={"rest": transport},
                                        policy=ExecutionPolicy(1000, max_pages, Path("fixture-policy.yaml")))
    return transport, registry, executor


def program(mode="detection", *, cone=False, tail="", window="10d"):
    location = "inside (120, -6, 5arcsec)\n" if cone else ""
    prefix = "" if mode == "detection" else mode + " "
    return f"objects from ztf via lasair\n{location}{prefix}within {window}\n{tail}"


def identities(portfolios):
    return {summary_object_identity(portfolio)[1] for portfolio in portfolios}


@pytest.mark.parametrize("cone", [False, True])
@pytest.mark.parametrize("mode,expected", [
    ("detection", {IDS[0], IDS[2], IDS[3]}), ("first", {IDS[2]}), ("last", {IDS[3]}),
])
def test_production_modes_select_candidates_from_their_own_required_evidence(graph, monkeypatch, cone, mode, expected):
    transport, registry, executor = replay(monkeypatch)
    result = execute_dsl(program(mode, cone=cone), graph=graph, registry=registry, executor=executor,
                         continue_from=None, reference_time=NOW)
    assert identities(result.portfolios) == expected
    histories = [p for name, p in transport.calls if name == "lightcurves"]
    assert len(histories) == (1 if mode == "detection" else 0)
    if mode == "detection":
        assert set(histories[0]["objectIds"].split(",")) == set(IDS[:4])
        for portfolio in result.portfolios:
            oid = summary_object_identity(portfolio)[1]
            records = [r for r in portfolio.records if r.semantic_type == "detection@ztf:lasair"]
            detections = [r for r in records if r.get("photometry.g.psf.mag") is not None]
            assert sorted(r.get("time.mjd") for r in detections) == HISTORY[oid]
            assert any(r.get("photometry.g.limit.mag") == 22.0 for r in records)
    assert result.run.steps[0].warnings == ()
    assert result.run.steps[0].time_reference == NOW
    assert identities(normalize_workflow_execution(result.staged.execution).steps[0].portfolios) == expected
    query_calls = [p for name, p in transport.calls if name == "query"]
    if cone:
        assert len(query_calls) == 1 and query_calls[0]["limit"] == 100
        assert all(plan.required for plan in result.run.steps[0].endpoint_plans)
    else:
        assert [p["offset"] for p in query_calls] == ([0, 2, 4] if mode == "detection" else [0])
        assert all(p["conditions"].count(" ORDER BY ") == 1 for p in query_calls)


@pytest.mark.parametrize("cone", [False, True])
def test_reuse_and_continuation_preserve_survivors_and_do_not_repeat_history(graph, monkeypatch, cone):
    transport, registry, executor = replay(monkeypatch)
    first = execute_dsl(program(cone=cone), graph=graph, registry=registry, executor=executor,
                        continue_from=None, reference_time=NOW)
    old_calls = len(transport.calls)
    second = execute_dsl("with lightcurve via lasair\n", graph=graph, registry=registry, executor=executor,
                         continue_from=first, reference_time=NOW + timedelta(days=1))
    assert len(transport.calls) == old_calls
    assert identities(second.portfolios) == {IDS[0], IDS[2], IDS[3]}
    assert second.run.steps[1].endpoint_plans[0].execution_reuse_from.plan_index == (2 if cone else 1)
    assert second.run.steps[0].time_reference == NOW
    third = execute_dsl("filter summary.detection_count >= 8\nwith lightcurve via lasair\n",
                        graph=graph, registry=registry, executor=executor, continue_from=second,
                        reference_time=NOW + timedelta(days=2))
    assert len(transport.calls) == old_calls + 1
    assert transport.calls[-1] == ("lightcurves", {"objectIds": IDS[3]})
    assert identities(third.portfolios) == {IDS[3]}


def test_batch_boundaries_preserve_full_execution_groups_on_reuse(graph, monkeypatch):
    ids = [f"ZTF20{chr(97 + i // 26)}{chr(97 + i % 26)}aaaaa" for i in range(51)]
    rows = [{**ROWS[0], "objectId": oid} for oid in ids]
    transport, registry, executor = replay(monkeypatch, rows=rows,
                                           histories={oid: [59000, 59012, 59030] for oid in ids}, page_size=100)
    result = execute_dsl(program(tail="with lightcurve via lasair\n"), graph=graph, registry=registry,
                         executor=executor, continue_from=None, reference_time=NOW)
    history_calls = [p for name, p in transport.calls if name == "lightcurves"]
    assert [len(p["objectIds"].split(",")) for p in history_calls] == [50, 1]
    assert identities(result.portfolios) == set(ids)
    assert len(result.staged.execution.steps[1].executions) == 2
    assert result.run.steps[0].execution_plan_indexes == (0, 1, 1)


def test_sql_window_conjoins_numeric_conditions_before_history_verification(graph, monkeypatch):
    transport, registry, executor = replay(monkeypatch)
    result = execute_dsl(program(tail="where summary.detection_count >= 8\n"), graph=graph,
                         registry=registry, executor=executor, continue_from=None, reference_time=NOW)
    assert identities(result.portfolios) == {IDS[3]}
    history, = (p for name, p in transport.calls if name == "lightcurves")
    assert set(history["objectIds"].split(",")) == {IDS[1], IDS[3]}
    assert all(p["conditions"].count(" ORDER BY ") == 1 for name, p in transport.calls if name == "query")


@pytest.mark.parametrize("mode", ["first", "last"])
def test_native_summary_dates_are_rechecked_if_the_server_ignores_sql(graph, monkeypatch, mode):
    _, registry, executor = replay(monkeypatch, ignore_sql=True)
    result = execute_dsl(program(mode), graph=graph, registry=registry, executor=executor,
                         continue_from=None, reference_time=NOW)
    assert identities(result.portfolios) == {IDS[2] if mode == "first" else IDS[3]}


@pytest.mark.parametrize("mode", ["detection", "first", "last"])
def test_closed_boundaries_and_empty_discovery(graph, monkeypatch, mode):
    row = {**ROWS[0], "jdmin": 2459010.5, "jdmax": 2459020.5}
    _, registry, executor = replay(monkeypatch, rows=[row], histories={IDS[0]: [59010, 59020]})
    result = execute_dsl(program(mode), graph=graph, registry=registry, executor=executor,
                         continue_from=None, reference_time=NOW)
    assert identities(result.portfolios) == {IDS[0]}
    transport, registry, executor = replay(monkeypatch, rows=[])
    empty = execute_dsl(program(mode), graph=graph, registry=registry, executor=executor,
                        continue_from=None, reference_time=NOW)
    assert empty.portfolios == () and [name for name, _ in transport.calls] == ["query"]


@pytest.mark.parametrize("failure", [None, "empty_history"])
def test_present_upper_limit_only_and_empty_histories_are_valid_negatives(graph, monkeypatch, failure):
    _, registry, executor = replay(monkeypatch, rows=ROWS[:1], histories={IDS[0]: []}, failure=failure)
    result = execute_dsl(program(), graph=graph, registry=registry, executor=executor,
                         continue_from=None, reference_time=NOW)
    assert result.portfolios == ()


@pytest.mark.parametrize("failure", ["omitted", "empty_batch", "duplicate", "foreign", "object_error",
                                     "missing_branch", "null_branch", "unknown_row", "history_request"])
def test_missing_or_failed_history_is_not_a_successful_empty_population(graph, monkeypatch, failure):
    _, registry, executor = replay(monkeypatch, failure=failure)
    error = WorkflowExecutionError if failure == "history_request" else TimeSelectionError
    with pytest.raises(error):
        execute_dsl(program(), graph=graph, registry=registry, executor=executor,
                    continue_from=None, reference_time=NOW)


@pytest.mark.parametrize("mode,failure", [("detection", "cone_error"), ("detection", "query_error"),
                                         ("first", "query_error"), ("last", "missing_summary")])
def test_cone_and_required_summary_errors_cannot_become_no_match(graph, monkeypatch, mode, failure):
    _, registry, executor = replay(monkeypatch, failure=failure)
    with pytest.raises((TimeSelectionError, ValueError)):
        execute_dsl(program(mode, cone=True), graph=graph, registry=registry, executor=executor,
                    continue_from=None, reference_time=NOW)


def test_pagination_policy_stops_before_partial_discovery_is_accepted(graph, monkeypatch):
    transport, registry, executor = replay(monkeypatch, max_pages=1)
    with pytest.raises(WorkflowExecutionError, match="execution-policy limit"):
        execute_dsl(program(), graph=graph, registry=registry, executor=executor,
                    continue_from=None, reference_time=NOW)
    assert [name for name, _ in transport.calls] == ["query"]


def test_historical_bounds_do_not_cap_an_objects_latest_detection(graph, monkeypatch):
    _, registry, executor = replay(monkeypatch)
    result = execute_dsl(program(window='["2020-06-10T00:00:00Z", "2020-06-20T00:00:00Z"]'),
                         graph=graph, registry=registry, executor=executor, continue_from=None,
                         reference_time=datetime(2026, 10, 29, tzinfo=timezone.utc))
    assert identities(result.portfolios) == {IDS[0], IDS[2], IDS[3]}


def test_native_summary_selection_uses_unchanged_captured_object_statistics(graph, monkeypatch):
    path = Path(__file__).parent / "fixtures/lasair/ztf/capture_20260813T110413Z/query_core.json"
    row = json.loads(path.read_text())[0]
    instant = datetime(1858, 11, 17, tzinfo=timezone.utc) + timedelta(days=row["jdmin"] - 2400000.5)
    window = f'["{(instant - timedelta(seconds=1)).isoformat()}", "{(instant + timedelta(seconds=1)).isoformat()}"]'
    _, registry, executor = replay(monkeypatch, rows=[row])
    result = execute_dsl(program("first", window=window), graph=graph, registry=registry,
                         executor=executor, continue_from=None)
    assert identities(result.portfolios) == {row["objectId"]}
    assert result.staged.execution.steps[0].executions[0].payload == [row]


def test_unmaterialized_cone_predicates_and_latest_remain_explicitly_deferred(graph):
    sources = [program(cone=True, tail="where summary.detection_count >= 8\n"),
               *(program(mode, tail="latest 1\n") for mode in ("detection", "first", "last"))]
    for source in sources:
        result = validate_dsl(source, graph=graph, continue_from=None)
        assert not result.is_runnable


@pytest.mark.parametrize("change", ["optional_history", "partition", "collection", "time_scale"])
def test_invalid_temporal_contracts_fail_loading(tmp_path, change):
    root = tmp_path / "providers"
    dest = root / "lasair/ztf"
    shutil.copytree(PROVIDERS_ROOT / "lasair/ztf", dest)
    paths = {name: dest / f"{name}.yaml" for name in ("capabilities", "mappings", "endpoints")}
    docs = {name: yaml.safe_load(path.read_text()) for name, path in paths.items()}
    recipe = docs["capabilities"]["recipes"]["semantic_search"][1]
    if change == "optional_history":
        recipe["calls"][1]["required"] = False
    elif change == "partition":
        docs["mappings"]["payloads"]["lightcurve_candidates"]["object_partition"]["field"] = None
    elif change == "collection":
        docs["endpoints"]["endpoints"]["lightcurves"]["params"]["objectIds"]["binding"]["collection"] = "adapter"
        docs["endpoints"]["endpoints"]["lightcurves"]["params"]["objectIds"]["binding"]["adapter"] = "alertissimo.data_layer.transforms.sql:string_membership_condition"
        docs["endpoints"]["endpoints"]["lightcurves"]["params"]["objectIds"]["binding"]["adapter_options"] = {
            "column": "objects.objectId", "value_pattern": r"^ZTF\d{2}[a-z]{7}$"}
    else:
        recipe["time_selection"]["time_scale"] = "tai"
    for name, path in paths.items():
        path.write_text(yaml.safe_dump(docs[name], sort_keys=False))
    with pytest.raises(CapabilityGraphError):
        build_capability_graph(root)
