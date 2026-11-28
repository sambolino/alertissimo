"""Scoped detection closure from audited history material, never mixed totals."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from itertools import count
import json
from pathlib import Path

import pytest
import yaml

from alertissimo.api import execute_dsl
from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.data_layer.runtime.recipes import RecipeRegistryError, load_provider_capabilities
from alertissimo.orchestration.normalization import normalize_workflow_execution
from alertissimo.orchestration.runtime import WorkflowExecutionError


PROVIDER = Path(__file__).parents[1] / "alertissimo/data_layer/providers/alerce/ztf"
OBJECT_ID = "ZTF18abbuksn"
COLLECTION = "lightcurve@ztf:alerce.points"
G = f"count({COLLECTION} where photometry.g.upper_limit = false)"
PROGRAM = f"object {OBJECT_ID} from ztf via alerce\nwith lightcurve\n"


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


class Executor:
    def __init__(self, *, extra=(), fail=False):
        self.calls, self.sequence, self.fail = [], count(), fail
        self.payload = {"detections": [
            {"oid": OBJECT_ID, "measurement_id": i, "candid": str(i), "mjd": 60000.0 + i,
             "fid": fid, "magpsf": 17.0 + i, "sigmapsf": 0.1, "drb": quality}
            for i, fid, quality in [(1, 1, 0.9), (2, 1, 0.1), (3, 2, 0.8)]
        ] + deepcopy(list(extra)), "non_detections": [
            {"oid": OBJECT_ID, "mjd": 59999.0, "fid": 1, "diffmaglim": 21.0},
        ]}

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        assert (broker, origin) == ("alerce", "ztf")
        params = dict(params or {})
        self.calls.append((endpoint, params))
        if endpoint == "query_object":
            payload = {"oid": OBJECT_ID, "meanra": 10.0, "meandec": 20.0}
        else:
            assert endpoint == "query_lightcurve"
            if self.fail:
                raise RuntimeError("required history failed")
            payload = deepcopy(self.payload)
        return ExecutionResult(payload=payload, execution_provenance=InternalExecutionProvenance(
            InternalExecutionId(f"complete:{next(self.sequence)}"), broker, origin, endpoint, params=params,
        ))


def selected(graph, condition, executor=None):
    return execute_dsl(PROGRAM + "filter " + condition, graph=graph,
                       executor=executor or Executor(), continue_from=None)


@pytest.mark.parametrize("condition", [
    G + " = 2", G + " <= 2", G + " < 3",
    f"count({COLLECTION} where photometry.r.upper_limit = false) = 1",
    f"count({COLLECTION} where photometry.g.upper_limit = false and quality.real_bogus >= 0.8) = 1",
    f"count({COLLECTION} where not (photometry.g.upper_limit = true)) = 2",
    f"count({COLLECTION} where photometry.g.upper_limit != true) = 2",
    f"count({COLLECTION} where photometry.g.upper_limit = false and photometry.g.psf.mag < 0) = 0",
    "for every {filter} in [g, r]: (count(" + COLLECTION
        + " where photometry.{filter}.upper_limit = false) >= 1)",
])
def test_detection_conditions_close_only_their_population(graph, condition):
    result = selected(graph, condition)
    assert len(result.portfolios) == 1
    # Independent final normalization must agree with staged selection.
    finalized = normalize_workflow_execution(result.staged.execution, graph=graph)
    assert len(finalized.steps[-1].portfolios) == 1


@pytest.mark.parametrize("condition", [
    f"count({COLLECTION}) = 4",
    f"count(measurement@ztf:alerce) = 4",
    f"min({COLLECTION}.photometry.g.psf.mag) > 0",
    f"count({COLLECTION} where photometry.g.upper_limit = false or time.mjd > 0) = 3",
    f"count({COLLECTION} where photometry.i.upper_limit = false) = 0",
    "for every {filter}: (count(" + COLLECTION + " where photometry.{filter}.upper_limit = false) >= 1)",
])
def test_mixed_totals_measurements_extrema_and_undelivered_bands_stay_open(graph, condition):
    assert selected(graph, condition).portfolios == ()


def test_continuation_preserves_parent_and_replays_no_provider_calls(graph):
    executor = Executor()
    parent = execute_dsl(PROGRAM, graph=graph, executor=executor, continue_from=None)
    before, calls = parent.to_dict(), deepcopy(executor.calls)
    continuation = execute_dsl("filter " + G + " = 2", graph=graph, executor=executor, continue_from=parent)
    assert len(continuation.portfolios) == 1
    assert executor.calls == calls and parent.to_dict() == before


def test_saved_history_closes_detection_count_without_removing_limit_points(graph):
    executor = Executor()
    executor.payload = json.loads((Path(__file__).parent / "fixtures/alerce/ztf/query_lightcurve.json").read_text())
    expected = sum(row["fid"] == 1 for row in executor.payload["detections"])
    result = selected(graph, G + f" = {expected}", executor)
    assert len(result.portfolios) == 1
    points = [point for record in result.portfolios[0].records
              if record.semantic_type == "lightcurve@ztf:alerce" for point in record.fields.get("points", ())]
    assert len(points) == len(executor.payload["detections"]) + len(executor.payload["non_detections"])


@pytest.mark.parametrize("row", [
    {}, {"mjd": 60004, "magpsf": 19.0},
    {"fid": 1, "magpsf": 19.0},
    {"fid": 99, "mjd": 60004, "magpsf": 19.0},
    {"fid": 1, "mjd": 60004, "magpsf": 19.0, "oid": "wrong-object"},
])
def test_dropped_unknown_status_or_misidentified_rows_prevent_closure(graph, row):
    assert selected(graph, G + " = 2", Executor(extra=(row,))).portfolios == ()


def test_missing_vetting_value_is_unknown_inside_an_otherwise_complete_population(graph):
    executor = Executor()
    del executor.payload["detections"][0]["drb"]
    condition = f"count({COLLECTION} where photometry.g.upper_limit = false and quality.real_bogus >= 0.8) = 0"
    assert selected(graph, condition, executor).portfolios == ()


def test_equal_time_duplicate_cannot_hide_a_lost_point_with_different_vetting(graph, monkeypatch):
    import importlib
    owner = importlib.import_module("alertissimo.orchestration.normalization.normalize")
    original = owner.normalize_execution

    def corrupt(execution, **kwargs):
        portfolios = original(execution, **kwargs)
        if execution.execution_provenance.endpoint != "query_lightcurve":
            return portfolios
        altered = []
        for portfolio in portfolios:
            records = []
            for record in portfolio.records:
                if record.semantic_type == "lightcurve@ztf:alerce":
                    points = list(record.fields["points"])
                    points[1] = points[0]
                    record = replace(record, fields={**record.fields, "points": tuple(points)})
                records.append(record)
            altered.append(replace(portfolio, records=tuple(records)))
        return tuple(altered)

    monkeypatch.setattr(owner, "normalize_execution", corrupt)
    executor = Executor()
    executor.payload["detections"][1]["mjd"] = executor.payload["detections"][0]["mjd"]
    condition = f"count({COLLECTION} where photometry.g.upper_limit = false and quality.real_bogus >= 0.8) = 2"
    assert selected(graph, condition, executor).portfolios == ()


def test_limits_without_detections_establish_zero_only_for_the_detection_subset(graph):
    executor = Executor()
    executor.payload["detections"] = []
    assert len(selected(graph, G + " = 0", executor).portfolios) == 1
    assert selected(graph, f"count({COLLECTION}) = 1", executor).portfolios == ()


def test_lsst_detection_status_does_not_supply_a_completeness_proof(graph):
    fixtures = Path(__file__).parent / "fixtures/fink/lsst"
    payloads = {name: json.loads((fixtures / (name + ".json")).read_text())[:1]
                for name in ("objects", "sources")}
    payloads["fp"] = []
    sequence = count()

    class LsstExecutor:
        def execute(self, broker, origin, endpoint, params=None, headers=None):
            assert (broker, origin) == ("fink", "lsst") and endpoint in payloads
            return ExecutionResult(payload=deepcopy(payloads[endpoint]), execution_provenance=InternalExecutionProvenance(
                InternalExecutionId(f"lsst-open:{next(sequence)}"), broker, origin, endpoint, params=params or {},
            ))

    oid = payloads["objects"][0]["r:diaObjectId"]
    source = (f"object {oid} from lsst via fink\nwith lightcurve\n"
              "filter count(lightcurve@lsst:fink.points where photometry.i.upper_limit = false) = 1")
    result = execute_dsl(source, graph=graph, executor=LsstExecutor(), continue_from=None)
    assert result.portfolios == ()


def test_delivery_alone_or_a_proof_without_delivery_never_closes_a_count(graph):
    no_proof = replace(graph, recipe_capabilities=tuple(
        replace(recipe, time_selection=None) if (recipe.broker, recipe.origin) == ("alerce", "ztf") else recipe
        for recipe in graph.recipe_capabilities))
    no_delivery = replace(graph, recipe_capabilities=tuple(
        replace(recipe, calls=tuple(replace(call, delivered_bands=()) for call in recipe.calls))
        for recipe in graph.recipe_capabilities))
    assert selected(no_proof, G + " = 2").portfolios == ()
    assert selected(no_delivery, G + " = 2").portfolios == ()


def test_required_history_failure_stays_visible(graph):
    with pytest.raises(WorkflowExecutionError, match="required history failed"):
        selected(graph, G + " = 2", Executor(fail=True))


def load_declaration(tmp_path, graph, delivery):
    document = yaml.safe_load((PROVIDER / "capabilities.yaml").read_text())
    document["delivered_bands"] = delivery
    path = tmp_path / "capabilities.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    endpoints = yaml.safe_load((PROVIDER / "endpoints.yaml").read_text())
    return load_provider_capabilities(path, graph, endpoints["endpoints"], broker="alerce", origin="ztf",
                                      transport_defaults=endpoints.get("transport_defaults"))


@pytest.mark.parametrize("delivery", [
    {"unknown_endpoint": {COLLECTION: ["g"]}},
    {"query_lightcurve": {"lightcurve@ztf:alerce.no_array": ["g"]}},
    {"query_object": {COLLECTION: ["g"]}},
    {"query_lightcurve": {COLLECTION: []}},
    {"query_lightcurve": {COLLECTION: ["g", "g"]}},
    {"query_lightcurve": {COLLECTION: ["u"]}},
    {"query_lightcurve": {COLLECTION: [1]}},
    {"query_lightcurve": {}},
    [], None,
])
def test_delivered_band_declarations_validate_endpoint_collection_and_domain(tmp_path, graph, delivery):
    with pytest.raises(RecipeRegistryError, match="delivered_bands"):
        load_declaration(tmp_path, graph, delivery)


def test_delivery_is_immutable_and_attached_only_to_its_declared_call(graph):
    recipes = graph.query_recipes(broker="alerce", origin="ztf", op="get_lightcurve")
    (recipe,) = recipes
    assert recipe.calls[0].delivered_bands == ((COLLECTION, ("g", "r")),)
    assert recipe.calls[1].delivered_bands == ()
    with pytest.raises(FrozenInstanceError):
        recipe.calls[0].delivered_bands = ()
