"""Fink's class-index window through real declarations and an offline transport.

The synthetic scan models the audited decimal-JD prefix bounds, not an HTTP
capture or a claim about the deployed Java client's version.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil

import pytest
import yaml

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import RegistryEndpointExecutor, TransportResult
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.runtime.capability_graph import CapabilityGraphError, build_capability_graph
from alertissimo.dsl import SurfaceLoweringError
from alertissimo.orchestration.ir import SearchSelection
from alertissimo.orchestration.normalization import TimeSelectionError, normalize_workflow_execution, summary_object_identity
from alertissimo.orchestration.planner import PlanningDeferredError, plan_step
from alertissimo.orchestration.runtime import WorkflowExecutionError


NOW = datetime(2020, 6, 20, tzinfo=timezone.utc)  # MJD 59020
IDS = tuple(f"ZTF20{letter * 7}" for letter in "abcde")
TEMPLATE = json.loads((Path(__file__).parent / "fixtures/fink/ztf/objects_core.json").read_text())[0]


def alert(oid, mjd, candid):
    return {**TEMPLATE, "i:objectId": oid, "i:jd": mjd + 2400000.5,
            "i:candid": candid, "i:fid": 1, "i:magpsf": 20.0,
            "v:classification": "SN candidate", "i:jdstarthist": 2458990.5,
            "i:jdendhist": 2459030.5}


ROWS = [alert(IDS[0], 59010, 1), alert(IDS[1], 59020, 2),
        alert(IDS[2], 59015, 3), alert(IDS[3], 59000, 4), alert(IDS[3], 59030, 5)]


def jd(value):
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (instant - datetime(1858, 11, 17, tzinfo=timezone.utc)).total_seconds() / 86400 + 2400000.5


def scan_rows(rows, params):
    # Lomikel's reversed range scan starts at the upper prefix and stops at
    # the byte-incremented lower prefix. Object suffixes sort after bare JDs.
    lower = f"{params['class']}_{jd(params['startdate'])}"
    lower = lower[:-1] + chr(ord(lower[-1]) + 1)
    upper = f"{params['class']}_{jd(params['stopdate'])}"
    return [row for row in rows if lower <= f"{params['class']}_{row['i:jd']}_{row['i:objectId']}" <= upper]


class ReplayTransport:
    name = "fixture"

    def __init__(self, rows=ROWS, *, enforce_scan=True, objects=None):
        self.rows = deepcopy(rows)
        self.objects = deepcopy(rows if objects is None else objects)
        self.enforce_scan = enforce_scan
        self.calls = []

    def execute(self, spec, params, headers=None):
        assert (spec.broker, spec.origin, spec.method) == ("fink", "ztf", "GET")
        self.calls.append((spec.endpoint, dict(params)))
        if spec.endpoint == "latests":
            assert "columns" not in params and "trend" not in params
            rows = scan_rows(self.rows, params) if self.enforce_scan else self.rows
        else:
            assert spec.endpoint == "objects"
            ids = set(params["objectId"].split(","))
            rows = [row for row in self.objects if row["i:objectId"] in ids]
        return TransportResult(deepcopy(rows), method="GET", status_code=200, content_type="application/json")


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def program(window="10d", tail=""):
    return ('objects from ztf via fink\n'
            f'within {window}\nwhere classification.best.class = "SN candidate"\n{tail}')


def execute(source, graph, transport, **kwargs):
    return execute_dsl(source, graph=graph, executor=RegistryEndpointExecutor(transports={"rest": transport}),
                       reference_time=NOW, continue_from=None, **kwargs)


def identities(portfolios):
    return {summary_object_identity(portfolio)[1] for portfolio in portfolios}


@pytest.mark.parametrize("window", ["10d", "[2020-06-10T02:00:00+02:00, 2020-06-20T02:00:00+02:00]"])
def test_closed_scientific_edges_survive_native_prefix_scanning(graph, window):
    transport = ReplayTransport()
    result = execute(program(window), graph, transport)
    assert identities(result.portfolios) == set(IDS[:3])
    params = transport.calls[0][1]
    assert params["startdate"] == "2020-06-09T21:00:00.000000Z"
    assert params["stopdate"] == "2020-06-20T03:00:00.000000Z"
    # Without the envelope, the audited prefix convention loses both exact
    # boundary alerts. This protects the physical translation, not just pruning.
    exact = {**params, "startdate": "2020-06-10T00:00:00Z", "stopdate": "2020-06-20T00:00:00Z"}
    assert {row["i:objectId"] for row in scan_rows(ROWS, exact)} == {IDS[2]}
    plan, = result.run.steps[0].endpoint_plans
    assert plan.time_selection.method == "native" and plan.time_selection.complete
    assert plan.time_selection.payload == "latests"
    assert result.run.steps[0].time_reference == NOW
    assert identities(normalize_workflow_execution(result.staged.execution).steps[0].portfolios) == set(IDS[:3])


@pytest.mark.parametrize("hour", [3, 12, 15])
def test_scan_envelope_covers_short_decimal_prefixes_at_other_times_of_day(graph, hour):
    rows = [alert(IDS[0], 59010 + hour / 24, 1), alert(IDS[1], 59020 + hour / 24, 2)]
    transport = ReplayTransport(rows)
    result = execute_dsl(program(), graph=graph, executor=RegistryEndpointExecutor(transports={"rest": transport}),
                         reference_time=NOW + timedelta(hours=hour), continue_from=None)
    assert identities(result.portfolios) == set(IDS[:2])


def test_exact_recheck_rejects_overlap_and_margin_only_candidates_before_retrieval(graph):
    rows = ROWS + [alert(IDS[4], 59009.95, 6), alert(IDS[4], 59020.05, 7)]
    transport = ReplayTransport(rows, enforce_scan=False,
                                objects=rows + [alert(IDS[0], 59040, 8)])
    result = execute(program(tail="with lightcurve via fink\nwith classification via fink\n"), graph, transport)
    assert identities(result.portfolios) == set(IDS[:3])
    retrievals = [params for endpoint, params in transport.calls if endpoint == "objects"]
    assert retrievals
    assert all(set(params["objectId"].split(",")) == set(IDS[:3]) for params in retrievals)
    survivor = next(p for p in result.portfolios if summary_object_identity(p)[1] == IDS[0])
    assert {r.get("time.mjd") for r in survivor.records
            if r.semantic_type == "detection@ztf:fink"} == {59010.0, 59040.0}


def test_cap_guard_runs_before_exact_temporal_pruning(graph):
    transport = ReplayTransport([alert(IDS[4], 59009.95, i) for i in range(100)])
    with pytest.raises(WorkflowExecutionError, match=r"incomplete result.*n=100"):
        execute(program(), graph, transport)
    assert [name for name, _ in transport.calls] == ["latests"]


def test_empty_native_window_is_a_complete_empty_result(graph):
    transport = ReplayTransport([])
    result = execute(program(), graph, transport)
    assert result.portfolios == ()
    assert [name for name, _ in transport.calls] == ["latests"]


def test_missing_time_is_unknown_instead_of_a_proven_negative(graph):
    row = alert(IDS[0], 59012, 1)
    row.pop("i:jd")
    transport = ReplayTransport([row], enforce_scan=False)
    with pytest.raises(TimeSelectionError, match="insufficient temporal evidence"):
        execute(program(), graph, transport)


def test_continuation_retains_exact_selection_and_the_original_clock(graph):
    transport = ReplayTransport()
    executor = RegistryEndpointExecutor(transports={"rest": transport})
    first = execute_dsl(program(), graph=graph, executor=executor, reference_time=NOW, continue_from=None)
    before = deepcopy(transport.calls)
    second = execute_dsl("with lightcurve via fink\n", graph=graph, executor=executor,
                         reference_time=NOW + timedelta(days=1), continue_from=first)
    assert transport.calls[:len(before)] == before
    assert not any(name == "latests" for name, _ in transport.calls[len(before):])
    assert identities(second.portfolios) == identities(first.portfolios) == set(IDS[:3])
    assert second.run.steps[0].time_reference == NOW
    assert second.run.steps[0].execution_ids == first.run.steps[0].execution_ids


@pytest.mark.parametrize("cone", [False, True])
@pytest.mark.parametrize("mode", ["first", "last"])
def test_first_last_are_not_inferred_from_an_alert_window(graph, cone, mode):
    source = program().replace("within 10d", f"{mode} within 10d")
    if cone:
        source = source.replace("within 10d", "within 10d\ninside (120, -6, 5arcsec)")
    transport = ReplayTransport()
    assert not validate_dsl(source, graph=graph, continue_from=None).is_runnable
    with pytest.raises(SurfaceLoweringError, match="candidate-time translation"):
        execute(source, graph, transport)
    assert transport.calls == []


def test_cone_window_does_not_inherit_the_ungrouped_class_scan_proof(graph):
    source = "objects from ztf via fink\ninside (120, -6, 5arcsec)\nwithin 10d\n"
    assert not validate_dsl(source, graph=graph, continue_from=None).is_runnable


@pytest.mark.parametrize("windowed", [False, True])
@pytest.mark.parametrize("label", ["SN candidate", "Early SN Ia candidate"])
def test_latest_needs_object_recency_even_with_a_complete_class_window(graph, windowed, label):
    source = program().replace("SN candidate", label)
    if not windowed:
        source = source.replace("within 10d\n", "")
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    step = validation.compilation.workflow.steps[0]
    with pytest.raises(PlanningDeferredError, match="latest requires"):
        plan_step(step.model_copy(update={"selection": SearchSelection(latest=1)}), graph)

    # A downstream history request happens after discovery selection. It must
    # not turn mapped per-alert history dates into an object-recency proof.
    source += "latest 1\nwith lightcurve via fink\n"
    assert not validate_dsl(source, graph=graph, continue_from=None).is_runnable
    transport = ReplayTransport()
    with pytest.raises(SurfaceLoweringError, match="latest requires") as raised:
        execute(source, graph, transport)
    assert raised.value.code == "deferred_capability"
    assert transport.calls == []


def test_class_alert_recency_can_rank_objects_differently_from_later_history(graph):
    a = alert(IDS[0], 59011, 1)
    b = alert(IDS[1], 59012, 2)
    a["i:jdendhist"], b["i:jdendhist"] = a["i:jd"], b["i:jd"]
    later_a = alert(IDS[0], 59019, 3)
    later_a["i:jdendhist"] = later_a["i:jd"]
    later_a["v:classification"] = "Unknown"
    transport = ReplayTransport([a, b], objects=[a, b, later_a])
    result = execute(program(tail="with lightcurve via fink\n"), graph, transport)

    def recencies(portfolios):
        return {summary_object_identity(p)[1]: max(
            r.get("time.last_mjd") for r in p.records
            if r.semantic_type == "summary@ztf:fink" and r.get("time.last_mjd") is not None
        ) for p in portfolios}

    discovery = recencies(normalize_workflow_execution(result.staged.execution).steps[0].portfolios)
    enriched = recencies(result.portfolios)
    assert discovery == {IDS[0]: 59011.0, IDS[1]: 59012.0}
    assert enriched == {IDS[0]: 59019.0, IDS[1]: 59012.0}
    assert max(discovery, key=discovery.get) == IDS[1]
    assert max(enriched, key=enriched.get) == IDS[0]
    assert identities(result.portfolios) == set(IDS[:2])
    assert [name for name, _ in transport.calls] == ["latests", "objects"]


@pytest.mark.parametrize("padding", [True, -1, "10800", float("inf"), float("nan"), 1e300])
def test_malformed_padding_fails_at_registry_loading(tmp_path, padding):
    root = tmp_path / "providers"
    destination = root / "fink/ztf"
    shutil.copytree(PROVIDERS_ROOT / "fink/ztf", destination)
    path = destination / "endpoints.yaml"
    doc = yaml.safe_load(path.read_text())
    doc["endpoints"]["latests"]["params"]["startdate"]["binding"]["adapter_options"]["padding_seconds"] = padding
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    with pytest.raises(CapabilityGraphError, match="padding_seconds"):
        build_capability_graph(root)


def test_padded_discovery_without_exact_selection_evidence_is_rejected(tmp_path):
    root = tmp_path / "providers"
    destination = root / "fink/ztf"
    shutil.copytree(PROVIDERS_ROOT / "fink/ztf", destination)
    path = destination / "capabilities.yaml"
    doc = yaml.safe_load(path.read_text())
    doc["recipes"]["semantic_search"][1].pop("time_selection")
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    with pytest.raises(CapabilityGraphError, match="padded discovery bounds require time_selection evidence"):
        build_capability_graph(root)
