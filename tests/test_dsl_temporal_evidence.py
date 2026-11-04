"""Compose existing temporal membership with later classification and latest.

Synthetic transports use production recipes, paging, binding and normalization.
No captured responses are changed and no live provider is contacted.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

import pytest

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import (
    ExecutionPolicy, ExecutionPolicyLimitError, RegistryEndpointExecutor, TransportResult,
)
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import SurfaceLoweringError
from alertissimo.orchestration.ir import WorkflowIR
from alertissimo.orchestration.normalization import (
    SearchSelectionError, TimeSelectionError, normalize_workflow_execution, summary_object_identity,
)
from alertissimo.orchestration.planner import PlanningDeferredError
from alertissimo.orchestration.runtime import WorkflowExecutionError


NOW = datetime(2020, 6, 20, tzinfo=timezone.utc)  # MJD 59020, window [59010, 59020]
IDS = tuple(f"ZTF20{letter * 7}" for letter in "abcdef")
HISTORY = {
    IDS[0]: [59000, 59012, 59080],  # In-window witness, classification rejects it.
    IDS[1]: [59000, 59090],         # Summary overlaps, but no in-window detection.
    IDS[2]: [59011, 59050],
    IDS[3]: [58990, 59015],
    IDS[4]: [59010, 59020],         # Both closed boundaries.
    IDS[5]: [59021, 59060],         # Entirely after the interval.
}
COUNTS = (7, 8, 3, 10, 5, 6)
TEMPORAL = {"detection": {IDS[0], IDS[2], IDS[3], IDS[4]},
            "first": {IDS[2], IDS[4]}, "last": {IDS[3], IDS[4]}}
QUALIFIED = 'classification@fink:fink.best.class = "SN candidate"'


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def identities(portfolios):
    return [summary_object_identity(portfolio)[1] for portfolio in portfolios]


def program(broker="alerce", mode="detection", latest=2, *, general=False, extra=""):
    mode_prefix = "" if mode == "detection" else mode + " "
    selection = "" if latest is None else f"latest {latest}\n"
    condition = (f"with classification via fink\nwhere {QUALIFIED}\n" if general else
                 'with classification via fink where best.class = "SN candidate"\n')
    return (f"objects from ztf via {broker}\ninside (124.88, -6.02, 5arcsec)\n"
            f"{mode_prefix}within 10d\n{selection}{condition}{extra}")


class TemporalTransport:
    def __init__(self, *, failure=None):
        self.failure, self.calls = failure, []
        self.rows = [{"oid": oid, "meanra": 124.88, "meandec": -6.02, "ndet": COUNTS[i],
                      "firstmjd": min(HISTORY[oid]), "lastmjd": max(HISTORY[oid])}
                     for i, oid in enumerate(IDS)]

    def history(self, oid, *, lasair=False):
        if self.failure == "history_request":
            raise RuntimeError("required history unavailable")
        if self.failure == "missing_history":
            return {"objectId": oid} if lasair else {"error": "missing history"}
        points = [{"candid": i + 1, "fid": 1, "magpsf": 20.0, "sigmapsf": 0.1,
                   **({"jd": date + 2400000.5} if lasair else {"oid": oid, "mjd": date})}
                  for i, date in enumerate(HISTORY[oid])]
        if lasair:
            # A gap candidate has both an upper limit and forced photometry
            # inside the interval. Neither is an ordinary detection witness.
            return {"objectId": oid,
                    "candidates": points + [{"jd": 2459012.5, "fid": 1, "diffmaglim": 22.0}],
                    "forcedphot": [{"jd": 2459012.5, "forcediffimflux": 123.0}]}
        return {"detections": points,
                "non_detections": [{"oid": oid, "mjd": 59012, "fid": 1, "diffmaglim": 22.0}]}

    def execute(self, spec, params, headers=None):
        params = deepcopy(dict(params))
        self.calls.append((spec.broker, spec.endpoint, params))
        assert spec.origin == "ztf"
        if spec.broker == "alerce":
            assert params["survey"] == "ztf" and params["format"] == "json"
            if spec.endpoint == "query_lightcurve":
                return TransportResult(self.history(params["oid"]))
            assert spec.endpoint == "query_objects"
            rows = deepcopy(self.rows)
            for name in ("firstmjd", "lastmjd"):
                bounds = params.get(name)
                if bounds is not None:
                    rows = [row for row in rows if row[name] >= bounds[0]
                            and (len(bounds) == 1 or row[name] <= bounds[1])]
            if "order_by" in params:
                rows.sort(key=lambda row: row[params["order_by"]], reverse=params["order_mode"] == "DESC")
            page, size = params.get("page", 1), params["page_size"]
            more = page * size < len(rows)
            return TransportResult({"items": rows[(page - 1) * size:page * size], "page": page,
                                    "has_next": more, "next": page + 1 if more else None})
        if spec.broker == "lasair":
            assert headers["Authorization"] == "Token fixture-only"
            if spec.endpoint == "cone":
                assert params["requestType"] == "all"
                return TransportResult([{"object": oid, "separation": 1.0} for oid in IDS])
            if spec.endpoint == "lightcurves":
                return TransportResult([self.history(oid, lasair=True) for oid in params["objectIds"].split(",")])
            assert spec.endpoint == "query"
            with sqlite3.connect(":memory:") as db:
                db.row_factory = sqlite3.Row
                db.execute("CREATE TABLE objects(objectId TEXT PRIMARY KEY, ramean REAL, decmean REAL, ncand INTEGER, jdmin REAL, jdmax REAL)")
                db.executemany("INSERT INTO objects VALUES (?, ?, ?, ?, ?, ?)", [
                    (r["oid"], r["meanra"], r["meandec"], r["ndet"],
                     r["firstmjd"] + 2400000.5, r["lastmjd"] + 2400000.5) for r in self.rows
                ])
                sql = f"SELECT {params['selected']} FROM {params['tables']} WHERE {params['conditions']} LIMIT ? OFFSET ?"
                rows = [dict(row) for row in db.execute(sql, (params["limit"], params["offset"]))]
            if self.failure == "missing_summary":
                rows = [row for row in rows if row["objectId"] != IDS[2]]
            return TransportResult(rows)
        assert (spec.broker, spec.endpoint) == ("fink", "objects")
        if self.failure == "classification_request":
            raise RuntimeError("required classification unavailable")
        return TransportResult([
            {"i:objectId": oid, "i:candid": 1000 + IDS.index(oid) * 10 + i,
             "i:jd": 2462000.5 + i, "i:fid": 1, "i:magpsf": 19.0, "i:sigmapsf": 0.1,
             "i:ra": 124.88, "i:dec": -6.02, "i:ndethist": 2,
             "i:jdendhist": 2400000.5 + (65000 if oid == IDS[3] else 64000),
             "v:classification": "AGN" if oid == IDS[0] else "SN candidate"}
            for oid in params["objectId"].split(",") for i in range(2)
        ])


def executor(monkeypatch, transport, *, max_pages=8):
    monkeypatch.setenv("LASAIR_ZTF_TOKEN", "fixture-only")
    return RegistryEndpointExecutor(transports={"python_client": transport, "rest": transport},
                                    policy=ExecutionPolicy(2, max_pages, Path("temporal-evidence-fixture")))


@pytest.mark.parametrize("broker", ["alerce", "lasair"])
@pytest.mark.parametrize("mode", ["detection", "first", "last"])
@pytest.mark.parametrize("latest", [None, 2])
def test_time_membership_precedes_classification_then_optional_latest(graph, monkeypatch, broker, mode, latest):
    source = program(broker, mode, latest)
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    transport = TemporalTransport()
    result = execute_dsl(source, graph=graph, executor=executor(monkeypatch, transport),
                         continue_from=None, reference_time=NOW)
    assert [step.op for step in result.workflow.steps] == ["cone_search", "get_classification", "filter"]
    assert result.workflow.steps[0].time_context.mode == mode
    assert result.workflow.steps[0].predicate is None
    assert result.run.steps[0].time_reference == result.staged.bindings[0].reference_time == NOW
    assert set(identities(result.result.steps[0].portfolios)) == TEMPORAL[mode]
    assert set(identities(result.result.steps[1].portfolios)) == TEMPORAL[mode]
    candidates = TEMPORAL[mode] - {IDS[0]}
    if latest is None:
        assert result.workflow.steps[0].selection is None
        assert set(identities(result.portfolios)) == candidates
    else:
        assert result.workflow.steps[0].selection.after_step == 2
        assert identities(result.portfolios) == sorted(candidates, key=lambda oid: (-max(HISTORY[oid]), oid))[:latest]
    fink_calls = [params for owner, _, params in transport.calls if owner == "fink"]
    assert len(fink_calls) == 1 and set(fink_calls[0]["objectId"].split(",")) == TEMPORAL[mode]
    history_calls = [params for _, name, params in transport.calls if name in {"query_lightcurve", "lightcurves"}]
    assert len(history_calls) == ((len(IDS) if broker == "alerce" else 1) if mode == "detection" else 0)
    for portfolio in result.portfolios:
        assert sum(record.semantic_type == "measurement@ztf:fink" for record in portfolio.records) == 2
        if mode == "detection":
            times = {record.get("time.mjd") for record in portfolio.records
                     if record.semantic_type == f"measurement@ztf:{broker}"}
            assert set(HISTORY[summary_object_identity(portfolio)[1]]) <= times
    rebuilt = normalize_workflow_execution(result.staged.execution)
    assert identities(rebuilt.steps[2].portfolios) == identities(result.portfolios)
    assert WorkflowIR.model_validate_json(result.workflow.model_dump_json()) == result.workflow


@pytest.mark.parametrize("broker", ["alerce", "lasair"])
def test_general_where_after_with_uses_the_same_window_and_selection(graph, monkeypatch, broker):
    transport = TemporalTransport()
    result = execute_dsl(program(broker, general=True), graph=graph, executor=executor(monkeypatch, transport),
                         continue_from=None, reference_time=NOW)
    assert identities(result.portfolios) == [IDS[2], IDS[4]]
    assert set(transport.calls[-1][2]["objectId"].split(",")) == TEMPORAL["detection"]


@pytest.mark.parametrize("broker", ["alerce", "lasair"])
def test_absolute_interval_does_not_move_with_a_later_reference_time(graph, monkeypatch, broker):
    source = program(broker).replace("within 10d", 'within ["2020-06-10T00:00:00Z", "2020-06-20T00:00:00Z"]')
    transport = TemporalTransport()
    result = execute_dsl(source, graph=graph, executor=executor(monkeypatch, transport),
                         continue_from=None, reference_time=NOW + timedelta(days=100))
    assert identities(result.portfolios) == [IDS[2], IDS[4]]
    assert set(transport.calls[-1][2]["objectId"].split(",")) == TEMPORAL["detection"]


def test_temporal_composition_still_requires_mapped_classification_fields(graph, monkeypatch):
    source = program().replace('best.class = "SN candidate"', "best.probability >= 0.8")
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_valid and not validation.is_runnable
    transport = TemporalTransport()
    with pytest.raises(SurfaceLoweringError, match="unmapped by its targeted retrieval"):
        execute_dsl(source, graph=graph, executor=executor(monkeypatch, transport), continue_from=None)
    assert transport.calls == []


@pytest.mark.parametrize("broker", ["alerce", "lasair"])
def test_continuation_preserves_clock_and_never_refills_a_filtered_latest(graph, monkeypatch, broker):
    transport = TemporalTransport()
    endpoint_executor = executor(monkeypatch, transport)
    first = execute_dsl(program(broker), graph=graph, executor=endpoint_executor,
                        continue_from=None, reference_time=NOW)
    snapshot, before = first.to_dict(), deepcopy(transport.calls)
    second = execute_dsl("with lightcurve via fink\n", graph=graph, executor=endpoint_executor,
                         continue_from=first, reference_time=NOW + timedelta(days=20))
    assert transport.calls[:-1] == before
    assert set(transport.calls[-1][2]["objectId"].split(",")) == {IDS[2], IDS[4]}
    assert second.run.steps[0].time_reference == NOW
    assert identities(second.portfolios) == [IDS[2], IDS[4]]
    old_calls = deepcopy(transport.calls)
    third = execute_dsl(f"filter summary@ztf:{broker}.detection_count >= 10\nwith lightcurve via fink\n",
                        graph=graph, executor=endpoint_executor, continue_from=second,
                        reference_time=NOW + timedelta(days=40))
    assert third.portfolios == ()  # D would match, but is outside the earlier latest 2.
    assert transport.calls == old_calls
    assert first.to_dict() == snapshot
    assert second.workflow.steps[:len(first.workflow.steps)] == first.workflow.steps
    assert third.workflow.steps[:len(second.workflow.steps)] == second.workflow.steps
    assert third.run.steps[0].time_reference == NOW


@pytest.mark.parametrize("broker", ["alerce", "lasair"])
def test_initial_history_reuse_cannot_resurrect_time_rejected_objects(graph, monkeypatch, broker):
    transport = TemporalTransport()
    result = execute_dsl(program(broker, latest=None, extra=f"with lightcurve via {broker}\n"),
                         graph=graph, executor=executor(monkeypatch, transport),
                         continue_from=None, reference_time=NOW)
    assert result.run.steps[2].endpoint_plans[0].execution_reuse_from is not None
    assert set(identities(result.result.steps[2].portfolios)) == TEMPORAL["detection"]
    assert set(identities(result.portfolios)) == {IDS[2], IDS[3], IDS[4]}
    histories = [name for _, name, _ in transport.calls if name in {"query_lightcurve", "lightcurves"}]
    assert len(histories) == (len(IDS) if broker == "alerce" else 1)


@pytest.mark.parametrize("broker", ["alerce", "lasair"])
@pytest.mark.parametrize("failure", ["missing_history", "history_request", "classification_request"])
def test_missing_required_evidence_never_becomes_a_partial_success(graph, monkeypatch, broker, failure):
    transport = TemporalTransport(failure=failure)
    with pytest.raises((TimeSelectionError, WorkflowExecutionError), match="history|temporal|classification"):
        execute_dsl(program(broker), graph=graph, executor=executor(monkeypatch, transport),
                    continue_from=None, reference_time=NOW)
    if failure != "classification_request":
        assert not any(owner == "fink" for owner, _, _ in transport.calls)


def test_pagination_exhaustion_stops_before_history_and_classification(graph, monkeypatch):
    transport = TemporalTransport()
    with pytest.raises(WorkflowExecutionError) as error:
        execute_dsl(program(), graph=graph, executor=executor(monkeypatch, transport, max_pages=1),
                    continue_from=None, reference_time=NOW)
    assert isinstance(error.value.__cause__, ExecutionPolicyLimitError)
    assert [name for _, name, _ in transport.calls] == ["query_objects"]


def test_lasair_required_summary_coverage_still_precedes_external_classification(graph, monkeypatch):
    transport = TemporalTransport(failure="missing_summary")
    with pytest.raises(SearchSelectionError, match="latest summary does not cover exactly"):
        execute_dsl(program("lasair"), graph=graph, executor=executor(monkeypatch, transport),
                    continue_from=None, reference_time=NOW)
    assert not any(owner == "fink" for owner, _, _ in transport.calls)


@pytest.mark.parametrize("broker,origin,evidence", [
    ("fink", "ztf", "lasair"), ("alerce", "lsst", "fink"), ("lasair", "lsst", "fink"),
])
def test_unproven_temporal_contracts_still_fail_before_provider_calls(graph, monkeypatch, broker, origin, evidence):
    source = (f"objects from {origin} via {broker}\ninside (124.88, -6.02, 5arcsec)\nwithin 10d\n"
              f'with classification via {evidence} where best.class = "SN"\n')
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_valid and not validation.is_runnable
    transport = TemporalTransport()
    with pytest.raises((SurfaceLoweringError, PlanningDeferredError)):
        execute_dsl(source, graph=graph, executor=executor(monkeypatch, transport), continue_from=None)
    assert transport.calls == []
