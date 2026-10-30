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
from alertissimo.orchestration.normalization import SearchSelectionError, TimeSelectionError, normalize_workflow_execution, summary_object_identity
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
    def __init__(self, ids=IDS, histories=HISTORY, *, failure=None, limits=True, limit_times=(59015,)):
        self.ids = ids
        self.histories = deepcopy(histories)
        self.failure = failure
        self.limits = limits
        self.limit_times = limit_times
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
            history.extend(alert(ztf_object_id, mjd, 999 + index, limit=True)
                           for index, mjd in enumerate(self.limit_times))
        locus = Locus(ztf_object_id, history)
        if self.failure == "missing":
            del locus.alerts
        elif self.failure == "collection":
            locus.alerts = None
        elif self.failure == "time":
            locus.alerts[0].mjd = None
        elif self.failure == "identity":
            locus.alerts[0].properties.pop("ztf_candid")
        elif self.failure == "photometry":
            locus.alerts[0].properties["ant_mag"] = "not numeric"
        elif self.failure == "omitted_mag":
            for row in locus.alerts:
                if row.properties["ant_survey"] == 2:
                    row.properties.pop("ant_mag")
        elif self.failure == "response_identity":
            locus.properties["ztf_object_id"] = "ZTF20foreign"
        return locus


def executor(monkeypatch, client, registry=None):
    monkeypatch.setitem(sys.modules, "antares_client.search", SimpleNamespace(
        search=client.search, get_by_ztf_object_id=client.get_by_ztf_object_id,
    ))
    return RegistryEndpointExecutor(registry=registry)


def program(window="10d", tail="", mode="detection"):
    prefix = "" if mode == "detection" else mode + " "
    return ("objects from ztf via antares\n"
            "where summary.position.ra >= 50 and summary.position.ra <= 51\n"
            f"{prefix}within {window}\n{tail}")


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
    assert proof.detection_identity == "measurement.identity.source_id"
    restored = EndpointPlan.model_validate_json(result.run.steps[0].endpoint_plans[0].model_dump_json())
    assert restored.time_selection == proof
    for portfolio in result.portfolios:
        oid = summary_object_identity(portfolio)[1]
        detections = [r for r in portfolio.records if r.semantic_type == "measurement@ztf:antares"]
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


@pytest.mark.parametrize("failure", ["null", "missing", "collection", "time", "identity", "photometry", "response_identity"])
def test_missing_history_or_unproven_detection_is_unknown_instead_of_a_negative(graph, monkeypatch, failure):
    client = NativeClient(ids=(IDS[2],), failure=failure)
    with pytest.raises(TimeSelectionError, match="temporal"):
        execute_dsl(program(), graph=graph, executor=executor(monkeypatch, client),
                    continue_from=None, reference_time=NOW)


@pytest.mark.parametrize("failure", [None, "omitted_mag"], ids=["null-magnitude", "absent-magnitude"])
def test_upper_limit_with_no_ordinary_magnitude_is_a_proven_negative(graph, monkeypatch, failure):
    client = NativeClient(ids=(IDS[4],), failure=failure)
    result = execute_dsl(program(), graph=graph, executor=executor(monkeypatch, client),
                         continue_from=None, reference_time=NOW)
    assert result.portfolios == ()
    assert [name for name, _ in client.calls] == ["search", "get_by_ztf_object_id"]


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
    (lambda r: r["time_selection"].update(detection_identity="measurement.identity.alert_id"), "detection_identity"),
])
def test_declared_evidence_must_be_required_and_map_the_origin_identity(tmp_path, change, message):
    root = contract(tmp_path, change)
    with pytest.raises(CapabilityGraphError, match=message):
        build_capability_graph(root)


def test_a_time_window_alone_does_not_replace_the_required_discovery_condition(graph):
    assert not validate_dsl("objects from ztf via antares\nwithin 10d\n",
                            graph=graph, continue_from=None).is_runnable


@pytest.mark.parametrize("mode,expected,reduction", [
    ("first", {IDS[1], IDS[2], IDS[3]}, "min"),
    ("last", {IDS[0], IDS[2], IDS[3]}, "max"),
])
@pytest.mark.parametrize("window", ["10d", "[2020-06-10T00:00:00Z, 2020-06-20T00:00:00Z]"])
def test_first_last_reduce_complete_unsorted_detection_history_and_ignore_limits(graph, monkeypatch, mode, expected, reduction, window):
    histories = {IDS[0]: [59012, 59005], IDS[1]: [59025, 59015],
                 IDS[2]: [59010], IDS[3]: [59020], IDS[4]: []}
    client = NativeClient(histories=histories, limit_times=(58900, 59100))
    endpoint_executor = executor(monkeypatch, client)
    source = program(window, mode=mode, tail="with lightcurve via antares\n")
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    result = execute_dsl(source, graph=graph, executor=endpoint_executor, continue_from=None, reference_time=NOW)
    assert identities(result.portfolios) == expected
    assert len(client.calls) == 1 + len(IDS)
    proof = result.run.steps[0].endpoint_plans[0].time_selection
    assert proof.reduction == reduction and proof.complete
    assert proof.response_identity == "properties.ztf_object_id"
    assert proof.target_parameter == "ztf_object_id" and proof.target_collection is None
    assert result.run.steps[1].endpoint_plans[0].execution_reuse_from == EndpointPlanRef(step_index=0, plan_index=1)
    for portfolio in result.portfolios:
        oid = summary_object_identity(portfolio)[1]
        records = [r for r in portfolio.records if r.semantic_type == "measurement@ztf:antares"]
        assert sorted(r.get("time.mjd") for r in records if r.get("identity.source_id") is not None) == sorted(histories[oid])
        assert sorted(r.get("time.mjd") for r in records if r.get("photometry.g.limit.mag") is not None) == [58900, 59100]
    assert identities(normalize_workflow_execution(result.staged.execution).steps[-1].portfolios) == expected
    previous_calls = deepcopy(client.calls)
    continued = execute_dsl("filter summary.position.ra >= 50.02\n", graph=graph,
                            executor=endpoint_executor, continue_from=result, reference_time=NOW + timedelta(days=1))
    assert client.calls == previous_calls
    assert identities(continued.portfolios) == {IDS[2], IDS[3]}
    assert continued.run.steps[0].time_reference == NOW


@pytest.mark.parametrize("mode", ["first", "last"])
@pytest.mark.parametrize("failure", ["time", "identity", "photometry", "response_identity"])
def test_first_last_cannot_ignore_unknown_history_even_with_an_in_window_detection(graph, monkeypatch, mode, failure):
    client = NativeClient(ids=(IDS[2],), histories={IDS[2]: [59010, 59015]}, failure=failure)
    with pytest.raises(TimeSelectionError, match="temporal"):
        execute_dsl(program(mode=mode), graph=graph, executor=executor(monkeypatch, client),
                    continue_from=None, reference_time=NOW)


@pytest.mark.parametrize("change", [
    {"reduction": "max"}, {"reduction": None}, {"complete": False}, {"detection_identity": None},
])
def test_extrema_proof_requires_matching_reduction_and_complete_identified_history(tmp_path, change):
    root = tmp_path / "providers"
    destination = root / "antares/ztf"
    shutil.copytree(PROVIDERS_ROOT / "antares/ztf", destination)
    path = destination / "capabilities.yaml"
    document = yaml.safe_load(path.read_text())
    recipe, = [r for r in document["recipes"]["semantic_search"] if r.get("time_selection", {}).get("mode") == "first"]
    recipe["time_selection"].update(change)
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    with pytest.raises(CapabilityGraphError, match="reduction requires"):
        build_capability_graph(root)


@pytest.mark.parametrize("mode,expected", [(None, IDS[1]), ("detection", IDS[0]),
                                           ("first", IDS[3]), ("last", IDS[3])])
def test_latest_ranks_complete_detection_history_after_membership(graph, monkeypatch, mode, expected):
    client = NativeClient(ids=IDS[:4], limit_times=(59150,))
    source = program(mode=mode or "detection", tail="latest 1\n")
    if mode is None:
        source = source.replace("within 10d\n", "")
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    result = execute_dsl(source, graph=graph, executor=executor(monkeypatch, client),
                         continue_from=None, reference_time=NOW)
    assert identities(result.portfolios) == {expected}
    assert [name for name, _ in client.calls] == ["search"] + ["get_by_ztf_object_id"] * 4
    assert [value for _, value in client.calls[1:]] == list(IDS[:4])
    plan = result.run.steps[0].endpoint_plans[0]
    proof = plan.latest_selection.history
    assert proof.mode == "last" and proof.reduction == "max" and proof.complete
    assert proof.evidence_plan_index == plan.latest_selection.evidence_plan_index == 1
    assert proof.response_identity == "properties.ztf_object_id" and proof.target_parameter == "ztf_object_id"
    assert plan.latest_selection.discovery_partition == plan.latest_selection.evidence_partition == "locus_id"
    # The serialized plan carries exactly the same ranking evidence for replay.
    assert EndpointPlan.model_validate_json(plan.model_dump_json()) == plan
    records = [r for r in result.portfolios[0].records if r.semantic_type == "measurement@ztf:antares"]
    assert sorted(r.get("time.mjd") for r in records if r.get("identity.source_id") is not None) == sorted(HISTORY[expected])
    assert [r.get("time.mjd") for r in records if r.get("photometry.g.limit.mag") is not None] == [59150]
    assert identities(normalize_workflow_execution(result.staged.execution).steps[0].portfolios) == {expected}


def test_latest_is_global_deduplicates_objects_and_breaks_ties_by_identity(graph, monkeypatch):
    # Deliberately reverse discovery order and repeat a locus/object. Upper-limit
    # dates cannot make the earlier object win the detection-time ranking.
    client = NativeClient(ids=(IDS[3], IDS[2], IDS[1], IDS[0], IDS[1]),
                          histories={IDS[0]: [59000], IDS[1]: [59020, 59001],
                                     IDS[2]: [59020], IDS[3]: [59010]}, limit_times=(59999,))
    source = program(tail="latest 2\n").replace("within 10d\n", "")
    result = execute_dsl(source, graph=graph, executor=executor(monkeypatch, client),
                         continue_from=None, reference_time=NOW)
    assert [summary_object_identity(p)[1] for p in result.portfolios] == [IDS[1], IDS[2]]
    assert sorted(value for _, value in client.calls[1:]) == sorted(IDS[:4])
    assert identities(normalize_workflow_execution(result.staged.execution).steps[0].portfolios) == {IDS[1], IDS[2]}


def test_latest_prunes_overbroad_root_rows_before_history_requests(graph, monkeypatch):
    class BroadClient(NativeClient):
        def search(self, query):
            yield from super().search(query)
            yield SimpleNamespace(locus_id="ANT-outside", ra=49.0, dec=37.0,
                                  properties={"ztf_object_id": IDS[1]})
            yield SimpleNamespace(locus_id="ANT-foreign", ra=50.0, dec=37.0,
                                  properties={"lsst_dia_object_id": "123"})
    client = BroadClient(ids=(IDS[0], IDS[2]))
    source = program(tail="latest 1\n").replace("within 10d\n", "")
    result = execute_dsl(source, graph=graph, executor=executor(monkeypatch, client),
                         continue_from=None, reference_time=NOW)
    assert identities(result.portfolios) == {IDS[0]}
    assert [value for _, value in client.calls[1:]] == [IDS[0], IDS[2]]
    assert identities(normalize_workflow_execution(result.staged.execution).steps[0].portfolios) == {IDS[0]}


@pytest.mark.parametrize("failure", ["null", "missing", "collection", "time", "identity", "photometry", "response_identity"])
def test_latest_rejects_missing_or_malformed_history_even_below_the_cutoff(graph, monkeypatch, failure):
    class BrokenClient(NativeClient):
        def get_by_ztf_object_id(self, ztf_object_id):
            self.failure = failure if ztf_object_id == IDS[0] else None
            return super().get_by_ztf_object_id(ztf_object_id)
    # B is newer than A. An incomplete A could hide an even newer detection.
    client = BrokenClient(ids=IDS[:2])
    source = program(tail="latest 1\n").replace("within 10d\n", "")
    with pytest.raises(SearchSelectionError, match="latest|temporal"):
        execute_dsl(source, graph=graph, executor=executor(monkeypatch, client),
                    continue_from=None, reference_time=NOW)


@pytest.mark.parametrize("limits", [False, True])
def test_latest_cannot_rank_a_candidate_with_no_detections(graph, monkeypatch, limits):
    client = NativeClient(ids=(IDS[4],), limits=limits)
    source = program(tail="latest 1\n").replace("within 10d\n", "")
    with pytest.raises(SearchSelectionError, match="complete valid detection recency"):
        execute_dsl(source, graph=graph, executor=executor(monkeypatch, client),
                    continue_from=None, reference_time=NOW)


def test_latest_empty_discovery_needs_no_history(graph, monkeypatch):
    client = NativeClient(ids=())
    source = program(tail="latest 1\n").replace("within 10d\n", "")
    result = execute_dsl(source, graph=graph, executor=executor(monkeypatch, client),
                         continue_from=None, reference_time=NOW)
    assert result.portfolios == () and len(client.calls) == 1
    assert normalize_workflow_execution(result.staged.execution).steps[0].portfolios == ()


def test_latest_continuation_replays_all_history_and_fetches_only_selected_ids(graph, monkeypatch):
    client = NativeClient()
    endpoint_executor = executor(monkeypatch, client)
    first = execute_dsl(program(tail="latest 2\n"), graph=graph, executor=endpoint_executor,
                        continue_from=None, reference_time=NOW)
    assert identities(first.portfolios) == {IDS[0], IDS[3]}
    calls = deepcopy(client.calls)
    second = execute_dsl("filter summary.position.ra >= 50.03\nwith lightcurve via antares\n",
                         graph=graph, executor=endpoint_executor, continue_from=first,
                         reference_time=NOW + timedelta(days=2))
    # Selection is a reuse barrier: the new retrieval is explicitly bound to D.
    assert client.calls == calls + [("get_by_ztf_object_id", IDS[3])]
    assert identities(second.portfolios) == {IDS[3]}
    assert identities(first.portfolios) == {IDS[0], IDS[3]}
    assert second.run.steps[0].time_reference == NOW
    assert second.run.steps[-1].endpoint_plans[0].execution_reuse_from is None
    assert identities(normalize_workflow_execution(second.staged.execution).steps[-1].portfolios) == {IDS[3]}


@pytest.mark.parametrize("change,message", [
    (lambda r: r["latest_selection"].update(complete=False), "complete finite discovery"),
    (lambda r: r["latest_selection"].update(call=0), "complete finite discovery"),
    (lambda r: r["latest_selection"]["history"].update(detection_identity=None), "reduction requires"),
    (lambda r: r["latest_selection"]["history"].update(payload="locus"), "mapped time evidence"),
    (lambda r: r["latest_selection"]["history"].update(time_scale="tai"), "time_scale"),
    (lambda r: r["calls"][1].update(required=False), "must be required"),
])
def test_latest_history_requires_a_complete_identified_required_contract(tmp_path, change, message):
    root = tmp_path / "providers"
    destination = root / "antares/ztf"
    shutil.copytree(PROVIDERS_ROOT / "antares/ztf", destination)
    path = destination / "capabilities.yaml"
    document = yaml.safe_load(path.read_text())
    recipe, = [r for r in document["recipes"]["semantic_search"]
               if "latest_selection" in r and "time_selection" not in r]
    change(recipe)
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    with pytest.raises(CapabilityGraphError, match=message):
        build_capability_graph(root)


@pytest.mark.parametrize("tail", ["within 10d\n", "first within 10d\n", "last within 10d\n", "latest 1\n"])
def test_native_cone_cannot_claim_unscoped_ztf_time_or_ranking(graph, tail):
    source = "objects from ztf via antares\ninside (50, 37, 5arcsec)\n" + tail
    assert not validate_dsl(source, graph=graph, continue_from=None).is_runnable


def test_latest_required_history_failure_is_owned_by_execution(graph, monkeypatch):
    client = NativeClient(ids=(IDS[0],), failure="request")
    source = program(tail="latest 1\n").replace("within 10d\n", "")
    with pytest.raises(WorkflowExecutionError, match="controlled required history failure"):
        execute_dsl(source, graph=graph, executor=executor(monkeypatch, client),
                    continue_from=None, reference_time=NOW)


@pytest.mark.parametrize("change", ["root_cap", "history_cap", "unscoped"])
def test_latest_cannot_claim_capped_or_unscoped_complete_discovery(tmp_path, change):
    root = tmp_path / "providers"
    destination = root / "antares/ztf"
    shutil.copytree(PROVIDERS_ROOT / "antares/ztf", destination)
    if change == "unscoped":
        path = destination / "capabilities.yaml"
        document = yaml.safe_load(path.read_text())
        for binding in document["predicate_bindings"]["search"]:
            binding["elasticsearch"].pop("identity_field")
        message = "identity-scoped"
    else:
        path = destination / "endpoints.yaml"
        document = yaml.safe_load(path.read_text())
        endpoint = "search" if change == "root_cap" else "get_by_ztf_object_id"
        document["endpoints"][endpoint]["params"]["limit"] = {
            "type": "int", "required": False, "default": 1, "role": "result_limit",
        }
        message = "uncapped|unfiltered"
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    with pytest.raises(CapabilityGraphError, match=message):
        build_capability_graph(root)


@pytest.mark.parametrize("failure", ["conflicting_discovery", "wrong_history_locus"])
def test_latest_rejects_ambiguous_or_wrong_locus_history_for_the_same_ztf_id(graph, monkeypatch, failure):
    class PartitionClient(NativeClient):
        def search(self, query):
            for locus in super().search(query):
                yield locus
                if failure == "conflicting_discovery":
                    other = Locus(IDS[0], [])
                    other.locus_id += "-other"
                    yield other
        def get_by_ztf_object_id(self, ztf_object_id):
            locus = super().get_by_ztf_object_id(ztf_object_id)
            if failure == "wrong_history_locus":
                locus.locus_id += "-other"
            return locus
    client = PartitionClient(ids=(IDS[0],))
    source = program(tail="latest 1\n").replace("within 10d\n", "")
    with pytest.raises(SearchSelectionError, match="latest history partition"):
        execute_dsl(source, graph=graph, executor=executor(monkeypatch, client),
                    continue_from=None, reference_time=NOW)
