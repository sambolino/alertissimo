"""Production ZTF temporal recipes with synthetic histories and a recorded client.

No live requests. The fake native client honors the audited inclusive ranges and
pagination protocol. Synthetic dates/identities make historical gaps explicit;
the separate captured-byte test leaves committed provider responses unchanged.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest
import yaml

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import ExecutionPolicy, RegistryEndpointExecutor
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.runtime.capability_graph import CapabilityGraphError, build_capability_graph
from alertissimo.orchestration.normalization import TimeSelectionError, normalize_workflow_execution, summary_object_identity
from alertissimo.orchestration.runtime import WorkflowExecutionError


NOW = datetime(2020, 6, 20, tzinfo=timezone.utc)  # UTC MJD 59020
IDS = tuple(f"ZTF20{letter * 7}" for letter in "abcdef")
ROWS = [
    {"oid": IDS[0], "firstmjd": 59000, "lastmjd": 59030},
    {"oid": IDS[1], "firstmjd": 59000, "lastmjd": 59090},
    {"oid": IDS[2], "firstmjd": 59011, "lastmjd": 59050},
    {"oid": IDS[3], "firstmjd": 58990, "lastmjd": 59015},
]
HISTORY = {IDS[0]: [59000, 59012, 59030], IDS[1]: [59000, 59090],
           IDS[2]: [59011, 59050], IDS[3]: [58990, 59015]}
FIXTURES = Path(__file__).parent / "fixtures/alerce/ztf"


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


class NativeClient:
    def __init__(self, *, rows=None, histories=None, broken=None, ignore_ranges=False):
        self.rows = deepcopy(ROWS if rows is None else rows)
        self.histories = deepcopy(HISTORY if histories is None else histories)
        self.broken, self.ignore_ranges = broken, ignore_ranges
        self.calls = []

    def query_objects(self, **params):
        assert params["survey"] == "ztf" and params["format"] == "json"
        self.calls.append(("query_objects", dict(params)))
        selected = deepcopy(self.rows)
        if not self.ignore_ranges:
            for name in ("firstmjd", "lastmjd"):
                bounds = params.get(name)
                if bounds is not None:
                    assert isinstance(bounds, list) and len(bounds) in (1, 2)
                    selected = [row for row in selected if row[name] >= bounds[0]
                                and (len(bounds) == 1 or row[name] <= bounds[1])]
        if params.get("order_by"):
            selected.sort(key=lambda row: row[params["order_by"]], reverse=params["order_mode"] == "DESC")
        # The real client defaults to page 1 when the first request omits page;
        # subsequent requests carry the explicit next page from this response.
        page, size = params.get("page", 1), params["page_size"]
        batch = selected[(page - 1) * size:page * size]
        more = page * size < len(selected)
        return {"items": batch, "page": page, "has_next": more,
                "next": page + 1 if more else None, "total": len(selected)}

    def query_lightcurve(self, oid, *, survey, format):
        assert survey == "ztf" and format == "json"
        self.calls.append(("query_lightcurve", {"oid": oid}))
        if self.broken == "request":
            raise RuntimeError("history unavailable")
        if self.broken == "missing":
            return {"error": "history unavailable"}
        payload = {"detections": [
            {"oid": oid, "mjd": mjd, "fid": 1, "candid": index + 1,
             "magpsf": 20.0, "sigmapsf": 0.1}
            for index, mjd in enumerate(self.histories[oid])
        ], "non_detections": [{"oid": oid, "mjd": 59012, "fid": 1, "diffmaglim": 22.0}]}
        if self.broken == "null":
            payload["detections"] = None
        return payload

    def query_forced_photometry(self, oid, *, survey, format):
        self.calls.append(("query_forced_photometry", {"oid": oid}))
        return []

    def query_probabilities(self, oid, *, survey, format):
        self.calls.append(("query_probabilities", {"oid": oid}))
        return []


def executor(monkeypatch, client, *, max_pages=8):
    monkeypatch.setitem(sys.modules, "alerce.core", SimpleNamespace(Alerce=lambda: client))
    return RegistryEndpointExecutor(policy=ExecutionPolicy(2, max_pages, Path("fixture-policy.yaml")))


def program(mode="detection", *, cone=False, tail="", window="10d"):
    location = "inside (124.88, -6.02, 5arcsec)\n" if cone else ""
    prefix = "" if mode == "detection" else mode + " "
    return f"objects from ztf via alerce\n{location}{prefix}within {window}\n{tail}"


def identities(portfolios):
    return {summary_object_identity(portfolio)[1] for portfolio in portfolios}


@pytest.mark.parametrize("cone", [False, True])
@pytest.mark.parametrize("mode,expected", [
    ("detection", {IDS[0], IDS[2], IDS[3]}), ("first", {IDS[2]}), ("last", {IDS[3]}),
])
def test_production_modes_have_distinct_membership_and_only_default_fetches_history(graph, monkeypatch, cone, mode, expected):
    client = NativeClient()
    result = execute_dsl(program(mode, cone=cone), graph=graph, executor=executor(monkeypatch, client),
                         continue_from=None, reference_time=NOW)
    assert identities(result.portfolios) == expected
    calls = [params for endpoint, params in client.calls if endpoint == "query_objects"]
    field = "firstmjd" if mode == "first" else "lastmjd"
    assert all(params[field] == ([59010.0] if mode == "detection" else [59010.0, 59020.0]) for params in calls)
    assert len(calls) == (2 if mode == "detection" else 1)
    if cone:
        assert all((params.get("ra"), params.get("dec"), params.get("radius")) == (124.88, -6.02, 5.0)
                   for params in calls)
    else:
        assert all("ra" not in params for params in calls)
    histories = [params["oid"] for endpoint, params in client.calls if endpoint == "query_lightcurve"]
    assert histories == (list(IDS[:4]) if mode == "detection" else [])
    assert result.run.steps[0].time_reference == NOW
    assert identities(normalize_workflow_execution(result.staged.execution).steps[0].portfolios) == expected


def test_history_is_reused_without_resurrection_and_continuation_retains_the_clock(graph, monkeypatch):
    client = NativeClient()
    endpoint_executor = executor(monkeypatch, client)
    first = execute_dsl(program(tail="with lightcurve via alerce\n"), graph=graph,
                        executor=endpoint_executor, continue_from=None, reference_time=NOW)
    expected = {IDS[0], IDS[2], IDS[3]}
    assert identities(first.portfolios) == expected
    assert first.run.steps[1].endpoint_plans[0].execution_reuse_from.plan_index == 1
    assert [p["oid"] for name, p in client.calls if name == "query_lightcurve"] == list(IDS[:4])
    assert {p["oid"] for name, p in client.calls if name == "query_forced_photometry"} == expected
    for portfolio in first.portfolios:
        oid = summary_object_identity(portfolio)[1]
        times = sorted(record.get("time.mjd") for record in portfolio.records
                       if record.internal_source is not None
                       and record.internal_source.payload_key == "query_lightcurve.detections")
        assert times == HISTORY[oid]  # Includes times outside the selected interval.
    old_calls = len(client.calls)
    second = execute_dsl("with classification via alerce\n", graph=graph, executor=endpoint_executor,
                         continue_from=first, reference_time=NOW + timedelta(days=1))
    assert len(client.calls) == old_calls + 3
    assert identities(second.portfolios) == expected
    assert second.run.steps[0].time_reference == NOW
    assert {params["oid"] for name, params in client.calls[old_calls:]} == expected


@pytest.mark.parametrize("mode,field,minimum,expected_bounds", [
    ("detection", "last_mjd", 59015, [59015.0]),
    ("detection", "last_mjd", 59005, [59010.0]),
    ("first", "first_mjd", 59015, [59015.0, 59020.0]),
    ("last", "last_mjd", 59015, [59015.0, 59020.0]),
    ("last", "last_mjd", 59025, [59025.0, 59020.0]),
])
def test_explicit_minima_intersect_the_window_instead_of_overwriting_it(graph, monkeypatch, mode, field, minimum, expected_bounds):
    client = NativeClient()
    result = execute_dsl(program(mode, tail=f"where summary.time.{field} >= {minimum}\n"),
                         graph=graph, executor=executor(monkeypatch, client), continue_from=None, reference_time=NOW)
    name = "firstmjd" if field == "first_mjd" else "lastmjd"
    assert all(params[name] == expected_bounds for endpoint, params in client.calls if endpoint == "query_objects")
    expected = {IDS[0], IDS[2], IDS[3]} if mode == "detection" else {IDS[3]} if mode == "last" and minimum == 59015 else set()
    assert identities(result.portfolios) == expected


def test_historical_window_accepts_newer_objects_only_with_an_inside_witness(graph, monkeypatch):
    rows = ROWS + [{"oid": IDS[4], "firstmjd": 59021, "lastmjd": 59060},
                   {"oid": IDS[5], "firstmjd": 58980, "lastmjd": 59009}]
    histories = {**HISTORY, IDS[4]: [59021, 59060], IDS[5]: [58980, 59009]}
    client = NativeClient(rows=rows, histories=histories)
    result = execute_dsl(program(window='["2020-06-10T00:00:00Z", "2020-06-20T00:00:00Z"]'),
                         graph=graph, executor=executor(monkeypatch, client), continue_from=None,
                         reference_time=datetime(2026, 10, 29, tzinfo=timezone.utc))
    assert identities(result.portfolios) == {IDS[0], IDS[2], IDS[3]}
    assert IDS[4] in [p["oid"] for name, p in client.calls if name == "query_lightcurve"]
    assert IDS[5] not in [p["oid"] for name, p in client.calls if name == "query_lightcurve"]


@pytest.mark.parametrize("mode", ["detection", "first", "last"])
def test_closed_boundaries_are_inclusive_for_every_production_mode(graph, monkeypatch, mode):
    client = NativeClient(rows=[{"oid": IDS[0], "firstmjd": 59010, "lastmjd": 59020}],
                          histories={IDS[0]: [59010, 59020]})
    result = execute_dsl(program(mode), graph=graph, executor=executor(monkeypatch, client),
                         continue_from=None, reference_time=NOW)
    assert identities(result.portfolios) == {IDS[0]}


@pytest.mark.parametrize("mode", ["first", "last"])
def test_native_summary_dates_are_rechecked_before_latest(graph, monkeypatch, mode):
    client = NativeClient(ignore_ranges=True)
    result = execute_dsl(program(mode, tail="latest 1\n"), graph=graph,
                         executor=executor(monkeypatch, client), continue_from=None, reference_time=NOW)
    assert identities(result.portfolios) == {IDS[2] if mode == "first" else IDS[3]}
    assert all(name == "query_objects" for name, _ in client.calls)


@pytest.mark.parametrize("broken", ["missing", "null", "request"])
def test_missing_evidence_or_failed_history_is_not_a_successful_empty_population(graph, monkeypatch, broken):
    client = NativeClient(rows=ROWS[:1], broken=broken)
    error = WorkflowExecutionError if broken == "request" else TimeSelectionError
    with pytest.raises(error, match="history unavailable|temporal evidence payload"):
        execute_dsl(program(), graph=graph, executor=executor(monkeypatch, client), continue_from=None, reference_time=NOW)


@pytest.mark.parametrize("empty_discovery", [False, True])
def test_present_empty_history_and_empty_discovery_are_valid(graph, monkeypatch, empty_discovery):
    client = NativeClient(rows=[] if empty_discovery else ROWS[:1], histories={IDS[0]: []})
    result = execute_dsl(program(), graph=graph, executor=executor(monkeypatch, client), continue_from=None, reference_time=NOW)
    assert result.portfolios == ()  # Non-detection at 59012 cannot supply a witness.


def test_pagination_limit_stops_before_partial_histories_are_accepted(graph, monkeypatch):
    client = NativeClient()
    with pytest.raises(WorkflowExecutionError, match="execution-policy limit"):
        execute_dsl(program(), graph=graph, executor=executor(monkeypatch, client, max_pages=1),
                    continue_from=None, reference_time=NOW)
    assert [name for name, _ in client.calls] == ["query_objects"]


def test_captured_history_membership_preserves_the_original_payload(graph, monkeypatch):
    data = json.loads((FIXTURES / "query_objects.json").read_text())["items"][:1]
    history = json.loads((FIXTURES / "query_lightcurve.json").read_text())
    mjd = history["detections"][0]["mjd"]
    instant = datetime(1858, 11, 17, tzinfo=timezone.utc) + timedelta(days=mjd)
    lower = (instant - timedelta(seconds=1)).isoformat()
    upper = (instant + timedelta(seconds=1)).isoformat()
    client = NativeClient(rows=data)
    def captured(oid, *, survey, format):
        client.calls.append(("query_lightcurve", {"oid": oid}))
        assert oid == data[0]["oid"]
        return deepcopy(history)
    client.query_lightcurve = captured
    result = execute_dsl(program(window=f'["{lower}", "{upper}"]'), graph=graph,
                         executor=executor(monkeypatch, client), continue_from=None)
    assert identities(result.portfolios) == {data[0]["oid"]}
    evidence = result.staged.execution.steps[0].executions[1]
    assert evidence.payload == history
    records = [record for portfolio in result.portfolios for record in portfolio.records
               if record.internal_source is not None and record.internal_source.payload_key == "query_lightcurve.detections"]
    assert len(records) == len(history["detections"])


@pytest.mark.parametrize("change", ["field", "mode", "constant", "missing_proof"])
def test_window_range_composition_requires_a_matching_declared_proof(tmp_path, change):
    root = tmp_path / "providers"
    destination = root / "alerce/ztf"
    shutil.copytree(PROVIDERS_ROOT / "alerce/ztf", destination)
    endpoint_path = destination / "endpoints.yaml"
    recipe_path = destination / "capabilities.yaml"
    endpoints, capabilities = yaml.safe_load(endpoint_path.read_text()), yaml.safe_load(recipe_path.read_text())
    recipe = capabilities["recipes"]["semantic_search"][1]
    if change == "field":
        endpoints["endpoints"]["query_objects"]["params"]["lastmjd"]["binding"]["adapter_options"]["field"] = "first"
    elif change == "mode":
        recipe["time_selection"]["mode"] = "first"
    elif change == "constant":
        recipe["calls"][0]["params"]["lastmjd"] = {"value": [59000]}
    else:
        recipe.pop("time_selection")
    endpoint_path.write_text(yaml.safe_dump(endpoints, sort_keys=False))
    recipe_path.write_text(yaml.safe_dump(capabilities, sort_keys=False))
    with pytest.raises(CapabilityGraphError):
        build_capability_graph(root)


def test_default_with_latest_remains_explicitly_deferred_until_composite_admission(graph):
    result = validate_dsl(program(tail="latest 1\n"), graph=graph, continue_from=None)
    assert not result.is_runnable
    assert result.lowering_error is not None
