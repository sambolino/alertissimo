"""Mixed broker histories close detection subsets only after row/identity audit."""

from copy import deepcopy
from dataclasses import replace
from itertools import count
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from alertissimo.api import execute_dsl
from alertissimo.data_layer.execution import EndpointRegistry, ExecutionResult
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.orchestration.normalization import normalize_workflow_execution, summary_object_identity
from alertissimo.orchestration.normalization.normalize import _component_empty_evidence, _detection_collection_evidence
from alertissimo.orchestration.runtime import WorkflowExecutionError


IDS = ("ZTF20aaaaaaa", "ZTF20bbbbbbb")
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def rows(broker, oid=IDS[0]):
    result = []
    for index, band, limit, quality in [(1, "g", False, 0.9), (2, "g", False, 0.1),
                                        (3, "r", False, 0.9), (4, "g", True, None), (5, "r", True, None)]:
        if broker == "lasair":
            row = {"jd": 2400000.5 + 60000 + index, "fid": 1 if band == "g" else 2,
                   "diffmaglim": 21.0, "magpsf": 21.0 if limit else 18.0 + index / 10}
            if not limit:
                row.update(candid=index, sigmapsf=0.1, drb=quality)
        else:
            properties = {"ztf_object_id": oid, "ant_passband": "g" if band == "g" else "R",
                          "ant_survey": 2 if limit else 1, "ant_maglim": 21.0}
            if not limit:
                properties.update(ztf_candid=index, ant_mag=18.0 + index / 10, ant_magerr=0.1, ztf_drb=quality)
            row = {"alert_id": f"{'ztf_upper_limit' if limit else 'ztf_candidate'}:{oid}:{index}",
                   "mjd": 60000.0 + index, "properties": properties}
        result.append(row)
    return result


class Executor:
    def __init__(self, broker, *, ids=IDS[:1], native=False, batch=None, fail=False):
        self.broker, self.native, self.batch, self.fail = broker, native, batch, fail
        self.calls, self.sequence = [], count()
        self.roots = {oid: ({"objectId": oid, "candidates": rows(broker, oid), "forcedphot": []}
                            if broker == "lasair" else {
                                "locus_id": "ANT-" + oid, "properties": {"ztf_object_id": oid},
                                "alerts": rows(broker, oid), "catalog_objects": {}, "ra": 10.0, "dec": 20.0,
                            }) for oid in ids}

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        assert origin == "ztf"
        params = deepcopy(dict(params or {}))
        self.calls.append((broker, endpoint, params))
        if broker == "alerce":
            assert endpoint == "query_object"
            payload = {"oid": params["oid"], "meanra": 10.0, "meandec": 20.0}
        else:
            assert broker == self.broker
            if self.fail:
                raise RuntimeError("controlled mixed-history failure")
            if broker == "lasair":
                assert endpoint == "lightcurves"
                payload = deepcopy(self.batch if self.batch is not None else
                                   [self.roots[oid] for oid in params["objectIds"].split(",")])
            else:
                assert endpoint == "get_by_ztf_object_id"
                payload = deepcopy(self.roots[params["ztf_object_id"]])
                if self.native:
                    payload["alerts"] = [SimpleNamespace(**row) for row in payload["alerts"]]
                    payload = SimpleNamespace(**payload)
        return ExecutionResult(payload=payload, execution_provenance=InternalExecutionProvenance(
            InternalExecutionId(f"mixed:{next(self.sequence)}"), broker, origin, endpoint, params=params,
        ))


def program(broker, ids=IDS[:1]):
    return "objects " + ", ".join(ids) + f" from ztf via alerce\nwith lightcurve via {broker}\n"


def count_g(broker):
    return f"count(lightcurve@ztf:{broker}.points where photometry.g.upper_limit = false)"


def selected(graph, broker, condition, executor=None, ids=IDS[:1]):
    return execute_dsl(program(broker, ids) + "filter " + condition, graph=graph,
                       executor=executor or Executor(broker, ids=ids), continue_from=None)


@pytest.mark.parametrize("broker,native", [("lasair", False), ("antares", False), ("antares", True)])
def test_mixed_histories_close_detection_counts_and_preserve_every_point(graph, broker, native):
    result = selected(graph, broker, count_g(broker) + " = 2", Executor(broker, native=native))
    assert len(result.portfolios) == 1
    points = [p for r in result.portfolios[0].records if r.semantic_type == f"lightcurve@ztf:{broker}"
              for p in r.fields["points"]]
    assert len(points) == 5
    assert sum(any(key.endswith(".upper_limit") and value is True for key, value in p.items()) for p in points) == 2
    normalized = normalize_workflow_execution(result.staged.execution, graph=graph)
    assert len(normalized.steps[-1].portfolios) == 1


@pytest.mark.parametrize("broker", ["lasair", "antares"])
def test_vetting_and_empty_detection_subsets_use_closed_bounds(graph, broker):
    condition = f"count(lightcurve@ztf:{broker}.points where photometry.g.upper_limit = false and quality.real_bogus >= 0.8) = 1"
    assert len(selected(graph, broker, condition).portfolios) == 1
    executor = Executor(broker)
    key = "candidates" if broker == "lasair" else "alerts"
    executor.roots[IDS[0]][key] = executor.roots[IDS[0]][key][-2:]
    assert len(selected(graph, broker, count_g(broker) + " = 0", executor).portfolios) == 1


@pytest.mark.parametrize("broker", ["lasair", "antares"])
@pytest.mark.parametrize("condition", ["mixed", "limits", "measurements"])
def test_mixed_totals_limits_and_measurement_collections_remain_open(graph, broker, condition):
    collection = f"lightcurve@ztf:{broker}.points"
    expression = {"mixed": f"count({collection}) = 5",
                  "limits": f"count({collection} where photometry.g.upper_limit = true) = 1",
                  "measurements": f"count(measurement@ztf:{broker}) = 5"}[condition]
    assert selected(graph, broker, expression).portfolios == ()


def test_declared_i_delivery_is_distinct_from_antares_unavailable_i(graph):
    for broker, expected in [("lasair", 1), ("antares", 0)]:
        condition = f"count(lightcurve@ztf:{broker}.points where photometry.i.upper_limit = false) = 0"
        assert len(selected(graph, broker, condition).portfolios) == expected


@pytest.mark.parametrize("broker", ["lasair", "antares"])
@pytest.mark.parametrize("bad", ["lost_row", "unknown_status", "unknown_band", "missing_time"])
def test_row_losses_or_unknowns_withhold_closure(graph, broker, bad):
    executor = Executor(broker)
    key = "candidates" if broker == "lasair" else "alerts"
    extra = deepcopy(executor.roots[IDS[0]][key][0])
    if bad == "lost_row":
        extra = {}
    elif broker == "lasair":
        if bad == "unknown_status":
            extra.pop("candid")
            extra.pop("diffmaglim")
        elif bad == "unknown_band":
            extra["fid"] = 99
        else:
            extra.pop("jd")
    else:
        if bad == "unknown_status":
            extra["properties"]["ant_survey"] = 99
        elif bad == "unknown_band":
            extra["properties"]["ant_passband"] = "X"
        else:
            extra.pop("mjd")
    executor.roots[IDS[0]][key].append(extra)
    assert selected(graph, broker, count_g(broker) + " = 2", executor).portfolios == ()


def test_reversed_batch_roots_keep_global_source_indices_bound_to_each_object(graph):
    executor = Executor("lasair", ids=IDS)
    executor.roots[IDS[1]]["candidates"] = executor.roots[IDS[1]]["candidates"][1:]
    executor.batch = [executor.roots[oid] for oid in reversed(IDS)]
    result = selected(graph, "lasair", count_g("lasair") + " = 2", executor, ids=IDS)
    assert [summary_object_identity(p)[1] for p in result.portfolios] == [IDS[0]]
    assert executor.calls[-1][2]["objectIds"] == ",".join(IDS)


@pytest.mark.parametrize("bad", ["missing_parent", "unexpected_parent", "duplicate_parent", "missing_identity", "missing_child", "null_child"])
def test_incomplete_batch_coverage_does_not_establish_exact_counts(graph, bad):
    executor = Executor("lasair", ids=IDS)
    parents = [deepcopy(executor.roots[oid]) for oid in IDS]
    if bad == "missing_parent":
        parents.pop()
    elif bad == "unexpected_parent":
        parents[1]["objectId"] = "ZTF-synthetic-unrequested"
    elif bad == "duplicate_parent":
        parents.append(deepcopy(parents[0]))
    elif bad == "missing_identity":
        parents[1] = {"candidates": [], "forcedphot": []}
    elif bad == "missing_child":
        parents[1].pop("candidates")
    else:
        parents[1]["candidates"] = None
    executor.batch = parents
    assert selected(graph, "lasair", count_g("lasair") + " = 2", executor, ids=IDS).portfolios == ()


@pytest.mark.parametrize("broker", ["lasair", "antares"])
def test_wholly_empty_history_proves_zero_in_delivered_detection_bands(graph, broker):
    executor = Executor(broker)
    executor.roots[IDS[0]]["candidates" if broker == "lasair" else "alerts"] = []
    assert len(selected(graph, broker, count_g(broker) + " = 0", executor).portfolios) == 1


def test_empty_and_nonempty_batch_parents_do_not_borrow_each_others_evidence(graph):
    executor = Executor("lasair", ids=IDS)
    executor.roots[IDS[0]]["candidates"] = []
    result = selected(graph, "lasair", count_g("lasair") + " = 0", executor, ids=IDS)
    assert [summary_object_identity(p)[1] for p in result.portfolios] == [IDS[0]]


def test_wholly_empty_alerce_history_uses_the_same_scoped_receipt_rule(graph):
    sequence = count()

    class EmptyAlerce:
        def execute(self, broker, origin, endpoint, params=None, headers=None):
            assert (broker, origin) == ("alerce", "ztf")
            if endpoint == "query_object":
                payload = {"oid": IDS[0], "meanra": 10.0, "meandec": 20.0}
            else:
                assert endpoint == "query_lightcurve"
                payload = {"detections": [], "non_detections": []}
            return ExecutionResult(payload=payload, execution_provenance=InternalExecutionProvenance(
                InternalExecutionId(f"empty-complete:{next(sequence)}"), broker, origin, endpoint, params=params or {},
            ))

    result = selected(graph, "alerce", count_g("alerce") + " = 0", EmptyAlerce())
    assert len(result.portfolios) == 1
    assert not any(r.semantic_type.startswith("lightcurve@") for r in result.portfolios[0].records)


@pytest.mark.parametrize("broker", ["lasair", "antares"])
def test_delivery_does_not_replace_a_material_detection_proof(graph, broker):
    without_proof = replace(graph, recipe_capabilities=tuple(
        replace(recipe, time_selection=None) if recipe.broker == broker else recipe
        for recipe in graph.recipe_capabilities))
    assert selected(without_proof, broker, count_g(broker) + " = 2").portfolios == ()


@pytest.mark.parametrize("broker", ["lasair", "antares"])
def test_continuation_is_immutable_and_does_not_make_new_provider_calls(graph, broker):
    executor = Executor(broker)
    parent = execute_dsl(program(broker), graph=graph, executor=executor, continue_from=None)
    before, calls = parent.to_dict(), deepcopy(executor.calls)
    result = execute_dsl("filter " + count_g(broker) + " = 2", graph=graph, executor=executor, continue_from=parent)
    assert len(result.portfolios) == 1 and executor.calls == calls and parent.to_dict() == before


@pytest.mark.parametrize("broker", ["lasair", "antares"])
def test_required_history_failure_remains_visible(graph, broker):
    with pytest.raises(WorkflowExecutionError, match="controlled mixed-history failure"):
        selected(graph, broker, count_g(broker) + " = 2", Executor(broker, fail=True))


@pytest.mark.parametrize("broker", ["lasair", "antares"])
def test_existing_captures_establish_detection_counts_without_losing_limit_rows(graph, broker):
    if broker == "lasair":
        root = json.loads((FIXTURES / "lasair/ztf/lightcurves_ZTF17aaabasp.json").read_text())[0]
        oid, key = root["objectId"], "candidates"
        expected = sum(row.get("candid") is not None and row["fid"] == 1 for row in root[key])
    else:
        folder = FIXTURES / "antares/ztf"
        root = json.loads((folder / "get_by_ztf_object_id.json").read_text())
        root["alerts"] = json.loads((folder / "alerts.json").read_text())
        root["catalog_objects"] = json.loads((folder / "catalog_objects.json").read_text())
        oid, key = root["properties"]["ztf_object_id"], "alerts"
        expected = sum(row["properties"]["ant_survey"] == 1 and row["properties"]["ant_passband"] == "g"
                       for row in root[key])
    executor = Executor(broker, ids=(oid,))
    executor.roots[oid] = root
    result = selected(graph, broker, count_g(broker) + f" = {expected}", executor, ids=(oid,))
    assert len(result.portfolios) == 1
    assert sum(len(r.fields["points"]) for r in result.portfolios[0].records
               if r.semantic_type == f"lightcurve@ztf:{broker}") == len(root[key])


def test_proof_inspection_never_invokes_an_unmaterialized_alerts_getter(graph):
    executor = Executor("antares", native=True)
    parent = selected(graph, "antares", count_g("antares") + " = 2", executor)
    physical = parent.staged.execution
    original = physical.steps[1].executions[0]

    class OpaqueHistory:
        @property
        def alerts(self):
            raise AssertionError("proof inspection invoked a lazy getter")

    steps = list(physical.steps)
    steps[1] = SimpleNamespace(executions=(ExecutionResult(payload=OpaqueHistory(),
                                                         execution_provenance=original.execution_provenance),))
    cache = {group.execution_id: group.portfolios for step in parent.staged.normalized.steps for group in step.executions}
    assert _component_empty_evidence(parent.run, steps, parent.portfolios, 2, graph, EndpointRegistry()) == {}
    assert _detection_collection_evidence(parent.run, steps, parent.portfolios, 2,
                                          graph, EndpointRegistry(), cache) == {}
