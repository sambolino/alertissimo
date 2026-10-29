"""Bounded ZTF object-summary discovery; no network or upstream client.

The first row is an unchanged Lasair capture; additional identities and summary
values are explicitly synthetic. SQLite independently executes the authored SQL
on those rows. It is a fixture engine, not a claim about deployed MySQL snapshots.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
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
from alertissimo.data_layer.transforms.sql import numeric_comparison
from alertissimo.orchestration.binding import bind_endpoint
from alertissimo.orchestration.ir import (
    BooleanPredicate, ComparisonPredicate, NotPredicate, PredicateLiteral,
    SearchSelection, SemanticReference, SemanticSearchStep, Source, TimeContext,
)
from alertissimo.orchestration.normalization import summary_object_identity
from alertissimo.orchestration.planner import PlanningDeferredError, plan_step
from alertissimo.orchestration.runtime import EndpointPlan, WorkflowExecutionError


FIXTURES = Path(__file__).parent / "fixtures/lasair/ztf"
PROJECTION = "objects.objectId,objects.ramean,objects.decmean,objects.ncand,objects.jdmin,objects.jdmax"


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def comparison(field="time.last_mjd", operator=">=", value=59190, **qualifiers):
    return ComparisonPredicate(left=SemanticReference(semantic_type="summary", field_path=field, **qualifiers),
                               operator=operator, right=PredicateLiteral(value=value))


def search(**kwargs):
    return SemanticSearchStep(semantic_type="summary", sources=[Source(broker="lasair", origin="ztf")], **kwargs)


def conjunction(*operands):
    return BooleanPredicate(operator="and", operands=operands)


@pytest.mark.parametrize("field,column,subtract", [
    ("detection_count", "ncand", 0), ("time.first_mjd", "jdmin", 2400000.5),
    ("time.last_mjd", "jdmax", 2400000.5),
])
@pytest.mark.parametrize("operator", ["=", "<", "<=", ">", ">="])
def test_numeric_operators_keep_units_qualifiers_and_serializable_plan(graph, field, column, subtract, operator):
    predicate = comparison(field, operator, 35, producer="ztf", channel="lasair")
    step = search(predicate=predicate)
    plan, = plan_step(step, graph)
    plan = EndpointPlan.model_validate_json(plan.model_dump_json())
    expression = f"(objects.{column} - {subtract})" if subtract else f"objects.{column}"
    assert plan.predicate_realization.params == {"conditions": f"{expression} {operator} 35 ORDER BY objects.objectId"}
    assert plan.predicate_realization.pushdown == plan.predicate_realization.residual == predicate
    bound = bind_endpoint(step, plan, EndpointRegistry())
    assert bound.params == {"selected": PROJECTION, "tables": "objects", **plan.predicate_realization.params}
    assert "offset" not in bound.params and "limit" not in bound.params
    # Existing target membership is still a separate physical encoder.
    assert bound.endpoint_spec.params["conditions"]["bind"] == "target_id"


def test_two_bounds_on_one_column_are_conjoined_and_reversed_operands_are_inverted(graph):
    lower = comparison(value=59190)
    upper = ComparisonPredicate(left=PredicateLiteral(value=59200), operator=">",
                                right=SemanticReference(semantic_type="summary", field_path="time.last_mjd"))
    predicate = conjunction(lower, upper)
    plan, = plan_step(search(predicate=predicate), graph)
    assert plan.predicate_realization.params == {"conditions": (
        "((objects.jdmax - 2400000.5) >= 59190) AND ((objects.jdmax - 2400000.5) < 59200) ORDER BY objects.objectId"
    )}
    assert plan.predicate_realization.residual == predicate


@pytest.mark.parametrize("predicate", [
    None, comparison(operator="!="), comparison(value=True), comparison(value="59190"),
    comparison(value=float("inf")), comparison(value="0; DROP TABLE objects"),
    comparison(channel="fink"), comparison(producer="fink"), comparison("position.ra"),
    NotPredicate(operand=comparison()),
    BooleanPredicate(operator="or", operands=(comparison(), comparison(value=59200))),
    conjunction(comparison(), comparison("position.dec")),
    conjunction(comparison(), comparison(value="59190")),
])
def test_ineligible_or_partially_translated_conditions_defer_before_binding(graph, predicate):
    with pytest.raises(PlanningDeferredError, match="eligible predicate assignment"):
        plan_step(search(predicate=predicate), graph)


@pytest.mark.parametrize("kwargs", [
    {"time_context": TimeContext(window=timedelta(days=7))},
    {"criteria": {"limit": 10}}, {"selection": SearchSelection(latest=1)},
])
def test_invalid_window_criteria_and_latest_are_not_relabelled_as_object_summary_search(graph, kwargs):
    with pytest.raises(PlanningDeferredError):
        plan_step(search(predicate=comparison(), **kwargs), graph)


class SmallPageRegistry(EndpointRegistry):
    def resolve(self, broker, origin, endpoint):
        spec = super().resolve(broker, origin, endpoint)
        if (broker, origin, endpoint) == ("lasair", "ztf", "query"):
            return replace(spec, params={**spec.params, "limit": {**spec.params["limit"], "default": 2}})
        return spec


class ReplayTransport:
    name = "fixture"

    def __init__(self, rows, *, error=False, ignore_conditions=False):
        self.rows = rows
        self.calls = []
        self.error = error
        self.ignore_conditions = ignore_conditions

    def execute(self, spec, params, headers=None):
        assert (spec.broker, spec.origin, spec.method, spec.request_encoding) == ("lasair", "ztf", "POST", "form")
        assert headers["Authorization"] == "Token fixture-only"
        self.calls.append((spec.endpoint, dict(params)))
        if spec.endpoint == "query":
            if self.error:
                return TransportResult({"error": "controlled query failure"}, status_code=200)
            with sqlite3.connect(":memory:") as db:
                db.row_factory = sqlite3.Row
                db.execute("CREATE TABLE objects(objectId TEXT PRIMARY KEY, ramean REAL, decmean REAL, ncand INTEGER, jdmin REAL, jdmax REAL)")
                db.executemany("INSERT INTO objects VALUES (:objectId,:ramean,:decmean,:ncand,:jdmin,:jdmax)", self.rows)
                conditions = "1=1 ORDER BY objects.objectId" if self.ignore_conditions else params["conditions"]
                query = f"SELECT {params['selected']} FROM {params['tables']} WHERE {conditions} LIMIT ? OFFSET ?"
                payload = [dict(row) for row in db.execute(query, (params["limit"], params["offset"]))]
        else:
            assert spec.endpoint == "lightcurves"
            captured = json.loads((FIXTURES / "lightcurves.json").read_text())[0]
            payload = [{**deepcopy(captured), "objectId": object_id} for object_id in params["objectIds"].split(",")]
        return TransportResult(payload, method="POST", status_code=200, content_type="application/json")


def recorded_and_synthetic_rows():
    original = json.loads((FIXTURES / "capture_20260813T110413Z/query_core.json").read_text())[0]
    return [original, {**original, "objectId": "ZTF20aaaaaaa", "ncand": 5, "jdmax": 2459196.0},
            {**original, "objectId": "ZTF20bbbbbbb", "ncand": 2, "jdmax": 2459198.0}]


def replay(monkeypatch, rows, *, max_pages=4, **kwargs):
    monkeypatch.setenv("LASAIR_ZTF_TOKEN", "fixture-only")
    transport = ReplayTransport(rows, **kwargs)
    registry = SmallPageRegistry()
    executor = RegistryEndpointExecutor(registry, transports={"rest": transport},
                                        policy=ExecutionPolicy(1000, max_pages, Path("fixture-policy.yaml")))
    return transport, registry, executor


def test_public_facade_exhausts_then_binds_only_survivors_and_retains_all_measurements(graph, monkeypatch):
    transport, registry, executor = replay(monkeypatch, recorded_and_synthetic_rows())
    source = "objects from ztf via lasair\nwhere summary.detection_count >= 5 and summary.time.last_mjd <= 59196\nwith lightcurve via lasair\n"
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    result = execute_dsl(source, graph=graph, registry=registry, executor=executor, continue_from=None)
    assert {summary_object_identity(p) for p in result.portfolios} == {("ztf", "ZTF20acpwljl"), ("ztf", "ZTF20aaaaaaa")}
    query_calls = [params for endpoint, params in transport.calls if endpoint == "query"]
    assert [params["offset"] for params in query_calls] == [0, 2]  # full page then empty proof
    assert all(params["selected"] == PROJECTION and params["tables"] == "objects" for params in query_calls)
    retrievals = [params for endpoint, params in transport.calls if endpoint == "lightcurves"]
    assert len(retrievals) == 1 and set(retrievals[0]["objectIds"].split(",")) == {"ZTF20acpwljl", "ZTF20aaaaaaa"}
    for portfolio in result.portfolios:
        detections = [record for record in portfolio.records if record.semantic_type == "detection@ztf:lasair"]
        assert len(detections) == 1
        # Measurement lies outside the object's admitted summary-time interval.
        assert detections[0].get("time.mjd") == 59000.0


def test_normalized_recheck_protects_against_a_server_ignoring_conditions(graph, monkeypatch):
    transport, registry, executor = replay(monkeypatch, recorded_and_synthetic_rows(), ignore_conditions=True)
    result = execute_dsl("objects from ztf via lasair\nwhere summary.detection_count >= 5\n",
                         graph=graph, registry=registry, executor=executor, continue_from=None)
    assert {summary_object_identity(p) for p in result.portfolios} == {("ztf", "ZTF20acpwljl"), ("ztf", "ZTF20aaaaaaa")}
    assert len(transport.calls) == 2  # 3 raw rows, then short page, then local pruning


@pytest.mark.parametrize("rows", [[], recorded_and_synthetic_rows()])
def test_complete_empty_and_nonempty_populations_are_distinct(graph, monkeypatch, rows):
    _, registry, executor = replay(monkeypatch, rows)
    result = execute_dsl("objects from ztf via lasair\nwhere summary.detection_count >= 0\n",
                         graph=graph, registry=registry, executor=executor, continue_from=None)
    assert len(result.portfolios) == len(rows)


@pytest.mark.parametrize("failure,kwargs,message", [
    ("policy", {"max_pages": 1}, "max_auto_pages"),
    ("provider", {"error": True}, "JSON array"),
])
def test_incomplete_or_error_discovery_never_becomes_a_successful_empty_result(graph, monkeypatch, failure, kwargs, message):
    _, registry, executor = replay(monkeypatch, recorded_and_synthetic_rows(), **kwargs)
    with pytest.raises(WorkflowExecutionError, match=message):
        execute_dsl("objects from ztf via lasair\nwhere summary.detection_count >= 0\n",
                    graph=graph, registry=registry, executor=executor, continue_from=None)


@pytest.mark.parametrize("change,message", [
    ("column", "mapped output and identity"), ("order", "qualified identifiers"),
    ("transform", "output mapping transform"), ("duplicate", "duplicate parameter"),
    ("projection", "constant mapped projection"), ("table", "one declared table"),
    ("offset", "automatic limit/offset"),
])
def test_invalid_sql_declarations_fail_at_loading(tmp_path, change, message):
    root = tmp_path / "providers"
    destination = root / "lasair/ztf"
    shutil.copytree(PROVIDERS_ROOT / "lasair/ztf", destination)
    path = destination / "capabilities.yaml"
    document = yaml.safe_load(path.read_text())
    binding = document["predicate_bindings"]["query"][0]
    params = document["recipes"]["semantic_search"][0]["calls"][0]["params"]
    if change == "column":
        binding["sql"]["column"] = "objects.not_a_column"
    elif change == "order":
        binding["sql"]["order_by"] = "objects.objectId; DROP TABLE objects"
    elif change == "transform":
        binding["sql"]["subtract"] = 2400000.5  # count is not a JD
    elif change == "duplicate":
        document["predicate_bindings"]["query"].append(deepcopy(binding))
    elif change == "projection":
        params["selected"]["value"] = "objects.objectId"
    elif change == "table":
        params["tables"]["value"] = "objects,sherlock_classifications"
    else:
        params["offset"] = {"value": 0}
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    with pytest.raises(CapabilityGraphError, match=message):
        build_capability_graph(root)


@pytest.mark.parametrize("value", [True, "3", "1 OR 1=1", float("inf"), float("nan")])
def test_numeric_sql_never_interpolates_text_or_nonfinite_literals(value):
    with pytest.raises(ValueError, match="finite numeric"):
        numeric_comparison("objects.ncand", ">=", value)


def test_possible_mapping_does_not_invent_unselected_classification_material(tmp_path):
    root = tmp_path / "providers"
    destination = root / "lasair/ztf"
    shutil.copytree(PROVIDERS_ROOT / "lasair/ztf", destination)
    path = destination / "mappings.yaml"
    document = yaml.safe_load(path.read_text())
    document["mappings"]["classification@sherlock:lasair.best.class"].append("query#classification")
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    graph = build_capability_graph(root)
    assert graph.fields_for_endpoint("lasair", "ztf", "query", semantic_record_noun="classification")
    recipe, = (item for item in graph.query_recipes(broker="lasair", origin="ztf", op="semantic_search")
               if item.time_selection is None)
    assert all(item.semantic_record_type == "summary@ztf:lasair" for item in recipe.calls[0].outputs)
