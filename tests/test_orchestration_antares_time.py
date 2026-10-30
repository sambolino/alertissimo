"""Default within over the native client's complete mixed alert history.

All rows and client calls are synthetic. Attribute-based payloads deliberately
exercise the same resolver surface as ANTARES Locus/Alert objects, without an
installed client, astropy objects, or network requests.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import shutil
import sys
from types import SimpleNamespace

import pytest
import yaml

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.runtime.capability_graph import CapabilityGraphError, build_capability_graph
from alertissimo.orchestration.normalization import TimeSelectionError, normalize_workflow_execution, summary_object_identity
from alertissimo.orchestration.runtime import EndpointPlan, EndpointPlanRef, WorkflowExecutionError


NOW = datetime(2020, 6, 20, tzinfo=timezone.utc)  # UTC MJD 59020
IDS = tuple(f"ZTF20{letter * 7}" for letter in "abcde")
HISTORY = {IDS[0]: [59000, 59012, 59030], IDS[1]: [59000, 59090],
           IDS[2]: [59010], IDS[3]: [59020], IDS[4]: []}
SURVIVORS = {IDS[0], IDS[2], IDS[3]}


def alert(oid, mjd, index, *, limit=False):
    properties = {"ztf_object_id": oid, "ant_passband": "g", "ant_survey": 2 if limit else 1,
                  "ant_mag": None if limit else 20.0, "ant_maglim": 22.0 if limit else None}
    if not limit:
        properties["ztf_candid"] = index + 100
    return SimpleNamespace(alert_id=f"{'ztf_upper' if limit else 'ztf_candidate'}:{index}",
                           mjd=mjd, properties=properties)


class Locus:
    def __init__(self, oid, alerts):
        self.locus_id = f"ANT-{oid}"
        self.properties = {"ztf_object_id": oid}
        self.ra, self.dec = 50 + IDS.index(oid) / 100, 37.0
        self.alerts = alerts
        self.catalog_objects = {}

    @property
    def lightcurve(self):
        raise AssertionError("the selected client lightcurve is not full-history evidence")


class NativeClient:
    def __init__(self, ids=IDS, histories=HISTORY, *, failure=None, limits=True):
        self.ids = ids
        self.histories = deepcopy(histories)
        self.failure = failure
        self.limits = limits
        self.calls = []

    def search(self, query):
        self.calls.append(("search", deepcopy(query)))
        yield from (Locus(oid, []) for oid in self.ids)

    def get_by_ztf_object_id(self, ztf_object_id):
        self.calls.append(("get_by_ztf_object_id", ztf_object_id))
        if self.failure == "request":
            raise RuntimeError("controlled required history failure")
        if self.failure == "null":
            return None
        history = [alert(ztf_object_id, mjd, index) for index, mjd in enumerate(self.histories[ztf_object_id])]
        if self.limits:
            history.append(alert(ztf_object_id, 59015, 999, limit=True))
        locus = Locus(ztf_object_id, history)
        if self.failure == "missing":
            del locus.alerts
        elif self.failure == "collection":
            locus.alerts = None
        elif self.failure == "time":
            locus.alerts[0].mjd = None
        elif self.failure == "identity":
            locus.alerts[0].properties.pop("ztf_candid")
        return locus


def executor(monkeypatch, client, registry=None):
    monkeypatch.setitem(sys.modules, "antares_client.search", SimpleNamespace(
        search=client.search, get_by_ztf_object_id=client.get_by_ztf_object_id,
    ))
    return RegistryEndpointExecutor(registry=registry)


def program(window="10d", tail=""):
    return ("objects from ztf via antares\n"
            "where summary.position.ra >= 50 and summary.position.ra <= 51\n"
            f"within {window}\n{tail}")


def identities(portfolios):
    return {summary_object_identity(p)[1] for p in portfolios}


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


@pytest.mark.parametrize("window", ["10d", "[2020-06-10T02:00:00+02:00, 2020-06-20T02:00:00+02:00]"])
def test_membership_uses_detections_closed_edges_and_keeps_full_histories(graph, monkeypatch, window):
    client = NativeClient()
    result = execute_dsl(program(window), graph=graph, executor=executor(monkeypatch, client),
                         continue_from=None, reference_time=NOW)
    assert identities(result.portfolios) == SURVIVORS
    assert [name for name, _ in client.calls] == ["search"] + ["get_by_ztf_object_id"] * len(IDS)
    assert {oid for _, oid in client.calls[1:]} == set(IDS)
    assert result.run.steps[0].time_reference == NOW
    proof = result.run.steps[0].endpoint_plans[0].time_selection
    assert proof.method == "material" and proof.complete and proof.evidence_plan_index == 1
    assert proof.detection_identity == "detection.identity.source_id"
    restored = EndpointPlan.model_validate_json(result.run.steps[0].endpoint_plans[0].model_dump_json())
    assert restored.time_selection == proof
    for portfolio in result.portfolios:
        oid = summary_object_identity(portfolio)[1]
        detections = [r for r in portfolio.records if r.semantic_type == "detection@ztf:antares"]
        assert sorted(r.get("time.mjd") for r in detections if r.get("identity.source_id") is not None) == HISTORY[oid]
        assert any(r.get("photometry.g.limit.mag") == 22 for r in detections)
    assert identities(normalize_workflow_execution(result.staged.execution).steps[0].portfolios) == SURVIVORS


def test_full_history_reuse_and_continuation_cannot_resurrect_rejected_ids(graph, monkeypatch):
    client = NativeClient()
    endpoint_executor = executor(monkeypatch, client)
    first = execute_dsl(program(), graph=graph, executor=endpoint_executor, continue_from=None, reference_time=NOW)
    original_calls = deepcopy(client.calls)
    second = execute_dsl("with lightcurve via antares\n", graph=graph, executor=endpoint_executor,
                         continue_from=first, reference_time=NOW + timedelta(days=1))
    assert client.calls == original_calls
    assert second.run.steps[1].endpoint_plans[0].execution_reuse_from == EndpointPlanRef(step_index=0, plan_index=1)
    assert identities(second.portfolios) == SURVIVORS
    assert second.run.steps[0].time_reference == NOW
    assert identities(normalize_workflow_execution(second.staged.execution).steps[-1].portfolios) == SURVIVORS
    third = execute_dsl("filter summary.position.ra >= 50.02\n", graph=graph, executor=endpoint_executor,
                        continue_from=second, reference_time=NOW + timedelta(days=2))
    assert client.calls == original_calls
    assert identities(third.portfolios) == {IDS[2], IDS[3]}
    assert identities(first.portfolios) == SURVIVORS
    assert third.run.steps[0].time_reference == NOW


def test_inline_history_reuse_fetches_no_second_lightcurve(graph, monkeypatch):
    client = NativeClient()
    result = execute_dsl(program(tail="with lightcurve via antares\n"), graph=graph,
                         executor=executor(monkeypatch, client), continue_from=None, reference_time=NOW)
    assert len(client.calls) == 1 + len(IDS)
    assert result.run.steps[1].endpoint_plans[0].execution_reuse_from == EndpointPlanRef(step_index=0, plan_index=1)
    assert identities(result.portfolios) == SURVIVORS


@pytest.mark.parametrize("ids", [(), (IDS[4],)])
def test_complete_empty_discovery_or_history_is_a_valid_empty_result(graph, monkeypatch, ids):
    client = NativeClient(ids=ids, limits=False)
    result = execute_dsl(program(), graph=graph, executor=executor(monkeypatch, client),
                         continue_from=None, reference_time=NOW)
    assert result.portfolios == ()
    assert len(client.calls) == 1 + len(ids)


@pytest.mark.parametrize("failure", ["null", "missing", "collection", "time", "identity"])
def test_missing_history_or_unproven_detection_is_unknown_instead_of_a_negative(graph, monkeypatch, failure):
    client = NativeClient(ids=(IDS[2],), failure=failure)
    with pytest.raises(TimeSelectionError, match="temporal"):
        execute_dsl(program(), graph=graph, executor=executor(monkeypatch, client),
                    continue_from=None, reference_time=NOW)


def test_required_history_request_failure_stops_execution(graph, monkeypatch):
    client = NativeClient(ids=(IDS[2],), failure="request")
    with pytest.raises(WorkflowExecutionError, match="controlled required history failure"):
        execute_dsl(program(), graph=graph, executor=executor(monkeypatch, client),
                    continue_from=None, reference_time=NOW)


def contract(tmp_path, change):
    root = tmp_path / "providers"
    destination = root / "antares/ztf"
    shutil.copytree(PROVIDERS_ROOT / "antares/ztf", destination)
    path = destination / "capabilities.yaml"
    document = yaml.safe_load(path.read_text())
    change(document["recipes"]["semantic_search"][1])
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    return root


def test_incomplete_history_cannot_prove_that_a_gap_candidate_does_not_match(tmp_path, monkeypatch):
    root = contract(tmp_path, lambda r: r["time_selection"].update(complete=False))
    registry = EndpointRegistry(root)
    client = NativeClient(ids=(IDS[1],))
    with pytest.raises(TimeSelectionError, match="insufficient temporal evidence"):
        execute_dsl(program(), graph=build_capability_graph(root), registry=registry,
                    executor=executor(monkeypatch, client, registry), continue_from=None, reference_time=NOW)


@pytest.mark.parametrize("change,message", [
    (lambda r: r["calls"][1].update(required=False), "required call"),
    (lambda r: r["time_selection"].update(detection_identity="detection.identity.alert_id"), "detection_identity"),
])
def test_declared_evidence_must_be_required_and_map_the_origin_identity(tmp_path, change, message):
    root = contract(tmp_path, change)
    with pytest.raises(CapabilityGraphError, match=message):
        build_capability_graph(root)


def test_a_time_window_alone_does_not_replace_the_required_discovery_condition(graph):
    assert not validate_dsl("objects from ztf via antares\nwithin 10d\n",
                            graph=graph, continue_from=None).is_runnable
