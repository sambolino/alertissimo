"""Bounded ZTF object-summary discovery; no network or upstream client.

The first row is an unchanged Lasair capture; additional identities and summary
values are explicitly synthetic. SQLite independently executes the authored SQL
on those rows. It is a fixture engine, not a claim about deployed MySQL snapshots.
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
from alertissimo.data_layer.transforms.sql import enum_comparison, numeric_comparison
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
    {"criteria": {"limit": 10}},
])
def test_invalid_window_and_criteria_are_not_relabelled_as_object_summary_search(graph, kwargs):
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
        detections = [record for record in portfolio.records if record.semantic_type == "measurement@ztf:lasair"]
        assert len(detections) == 1
        # Measurement lies outside the object's admitted summary-time interval.
        assert detections[0].get("time.mjd") == 59000.0


def test_normalized_recheck_protects_against_a_server_ignoring_conditions(graph, monkeypatch):
    transport, registry, executor = replay(monkeypatch, recorded_and_synthetic_rows(), ignore_conditions=True)
    result = execute_dsl("objects from ztf via lasair\nwhere summary.detection_count >= 5\n",
                         graph=graph, registry=registry, executor=executor, continue_from=None)
    assert {summary_object_identity(p) for p in result.portfolios} == {("ztf", "ZTF20acpwljl"), ("ztf", "ZTF20aaaaaaa")}
    assert len(transport.calls) == 2  # 3 raw rows, then short page, then local pruning


def test_numeric_discovery_latest_exhausts_identity_order_before_ranking(graph, monkeypatch):
    rows = recorded_and_synthetic_rows()
    transport, registry, executor = replay(monkeypatch, rows)
    result = execute_dsl("objects from ztf via lasair\nwhere summary.detection_count >= 0\nlatest 1\nwith lightcurve via lasair\n",
                         graph=graph, registry=registry, executor=executor, continue_from=None)
    expected = sorted(rows, key=lambda row: (-row["jdmax"], row["objectId"]))[0]["objectId"]
    assert {summary_object_identity(p)[1] for p in result.portfolios} == {expected}
    queries = [p for name, p in transport.calls if name == "query"]
    assert [p["offset"] for p in queries] == [0, 2]
    assert all(p["limit"] == 2 and p["conditions"].endswith("ORDER BY objects.objectId") for p in queries)
    assert [p for name, p in transport.calls if name == "lightcurves"] == [{"objectIds": expected}]


@pytest.mark.parametrize("change", ["offset_default", "offset_role", "ordering", "no_sql"])
def test_offset_latest_requires_an_exhaustive_stable_sql_contract(tmp_path, change):
    root = tmp_path / "providers"
    destination = root / "lasair/ztf"
    shutil.copytree(PROVIDERS_ROOT / "lasair/ztf", destination)
    endpoints_path, capabilities_path = destination / "endpoints.yaml", destination / "capabilities.yaml"
    endpoints, capabilities = yaml.safe_load(endpoints_path.read_text()), yaml.safe_load(capabilities_path.read_text())
    if change == "offset_default":
        endpoints["endpoints"]["query"]["params"]["offset"]["default"] = 2
    elif change == "offset_role":
        endpoints["endpoints"]["query"]["params"]["offset"].pop("role")
    elif change == "ordering":
        capabilities["selection_bindings"]["query"]["latest"]["params"] = {"limit": {"value": 1}}
    else:
        # Omit SQL translations without introducing an invalid empty binding
        # list, so the selection contract's ordering guard is what fails.
        capabilities["predicate_bindings"].pop("query")
    endpoints_path.write_text(yaml.safe_dump(endpoints, sort_keys=False))
    capabilities_path.write_text(yaml.safe_dump(capabilities, sort_keys=False))
    message = "offset latest requires mapped SQL identity ordering" if change == "no_sql" else "selection_bindings"
    with pytest.raises(CapabilityGraphError, match=message):
        build_capability_graph(root)


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
    assert "query#classification" in document["mappings"]["classification@sherlock:lasair.best.class"]
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    graph = build_capability_graph(root)
    assert graph.fields_for_endpoint("lasair", "ztf", "query", semantic_record_noun="classification")
    recipe, = (item for item in graph.query_recipes(broker="lasair", origin="ztf", op="semantic_search")
               if item.time_selection is None and item.calls[0].sql_join is None)
    assert all(item.semantic_record_type == "summary@ztf:lasair" for item in recipe.calls[0].outputs)


SHERLOCK_LABELS = ("AGN", "BS", "CV", "NT", "ORPHAN", "SN", "UNCLEAR", "VS")
NOW = datetime(2020, 6, 20, tzinfo=timezone.utc)  # MJD 59020
JOIN_PROJECTION = PROJECTION + ",sherlock_classifications.classification,sherlock_classifications.classificationReliability,sherlock_classifications.description"


def sherlock_population(label="AGN"):
    """Explicitly synthetic keys, summaries and context on a captured template."""
    template = recorded_and_synthetic_rows()[0]
    rows = [{**template, "objectId": f"ZTF20{letter * 7}", "ncand": 8,
             "jdmin": 2459011.5, "jdmax": 2459000.5 + mjd - 59000}
            for letter, mjd in zip("abcdefgh", (59018, 59019, 59019.5, 59020, 59019.9, 59019.8, 59030, 59000))]
    rows[-1]["jdmin"] = 2458990.5
    labels = (label, label, None, "absent", "CV" if label != "CV" else "SN", label.lower(), label, label)
    contexts = [{"objectId": row["objectId"], "classification": value,
                 "classificationReliability": 2, "description": f"Synthetic {value} context"}
                for row, value in zip(rows, labels) if value != "absent"]
    return rows, contexts


class SherlockReplayTransport(ReplayTransport):
    def __init__(self, rows, contexts, **kwargs):
        super().__init__(rows, **kwargs)
        self.contexts = contexts

    def execute(self, spec, params, headers=None):
        if spec.endpoint == "query":
            self.calls.append((spec.endpoint, dict(params)))
            if self.error:
                return TransportResult({"error": "controlled join failure"}, status_code=200)
            with sqlite3.connect(":memory:") as db:
                db.row_factory = sqlite3.Row
                db.execute("CREATE TABLE objects(objectId TEXT PRIMARY KEY, ramean REAL, decmean REAL, ncand INTEGER, jdmin REAL, jdmax REAL)")
                db.executemany("INSERT INTO objects VALUES (:objectId,:ramean,:decmean,:ncand,:jdmin,:jdmax)", self.rows)
                # NOCASE deliberately models a broader equality than Python.
                # This verifies the residual, not deployed MySQL SQL-mode parity.
                db.execute("CREATE TABLE sherlock_classifications(objectId TEXT PRIMARY KEY, classification TEXT COLLATE NOCASE, classificationReliability INTEGER, description TEXT)")
                db.executemany("INSERT INTO sherlock_classifications VALUES (:objectId,:classification,:classificationReliability,:description)", self.contexts)
                conditions = params["conditions"]
                if self.ignore_conditions:
                    conditions = ("objects.objectId = sherlock_classifications.objectId "
                                  if "sherlock_classifications" in params["tables"] else "1=1 ") + "ORDER BY objects.objectId"
                # Independently execute the explicit identity join, filters,
                # ordering and pagination compiled by the production planner.
                query = f"SELECT {params['selected']} FROM {params['tables']} WHERE {conditions} LIMIT ? OFFSET ?"
                payload = [dict(row) for row in db.execute(query, (params["limit"], params["offset"]))]
        elif spec.endpoint == "objects":
            self.calls.append((spec.endpoint, dict(params)))
            ids = set(params["objectIds"].split(","))
            contexts = {row["objectId"]: row for row in self.contexts}
            payload = [{"objectId": row["objectId"], "objectData": row,
                        "sherlock": contexts.get(row["objectId"], {})} for row in self.rows if row["objectId"] in ids]
        else:
            assert spec.endpoint == "lightcurves"
            self.calls.append((spec.endpoint, dict(params)))
            template = json.loads((FIXTURES / "lightcurves.json").read_text())[0]
            payload = []
            for object_id in params["objectIds"].split(","):
                item = {**deepcopy(template), "objectId": object_id}
                # Keep the original outside-window measurement and add a
                # synthetic in-window witness for detection-mode coverage.
                item["candidates"].append({**item["candidates"][0], "candid": 2, "jd": 2459015.5})
                payload.append(item)
        return TransportResult(payload, status_code=200, method="POST", content_type="application/json")


def sherlock_replay(monkeypatch, label="AGN", *, max_pages=8, **kwargs):
    monkeypatch.setenv("LASAIR_ZTF_TOKEN", "fixture-only")
    transport = SherlockReplayTransport(*sherlock_population(label), **kwargs)
    registry = SmallPageRegistry()
    executor = RegistryEndpointExecutor(registry, transports={"rest": transport},
                                        policy=ExecutionPolicy(1000, max_pages, Path("fixture-policy.yaml")))
    return transport, registry, executor


@pytest.mark.parametrize("label", SHERLOCK_LABELS)
@pytest.mark.parametrize("reference", ["classification.best.class", "classification@sherlock:lasair.best.class"])
def test_native_sherlock_join_matches_complete_local_filter(graph, monkeypatch, label, reference):
    transport, registry, executor = sherlock_replay(monkeypatch, label)
    native = f'objects from ztf via lasair\nlast within 10d\nwhere {reference} = "{label}"\nwith lightcurve via lasair\n'
    validation = validate_dsl(native, graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    result = execute_dsl(native, graph=graph, registry=registry, executor=executor, reference_time=NOW, continue_from=None)
    identities = {summary_object_identity(p) for p in result.portfolios}
    assert identities == {("ztf", "ZTF20aaaaaaa"), ("ztf", "ZTF20bbbbbbb")}
    queries = [params for name, params in transport.calls if name == "query"]
    assert [p["offset"] for p in queries] == [0, 2]
    assert all(p["selected"] == JOIN_PROJECTION and p["tables"] == "objects,sherlock_classifications" for p in queries)
    assert all(p["conditions"].count(" ORDER BY ") == 1 and 'objects.objectId = sherlock_classifications.objectId' in p["conditions"] for p in queries)
    assert all(f'sherlock_classifications.classification = "{label}"' in p["conditions"] for p in queries)
    # Native case-insensitive equality also returned lowercase F; recheck
    # prunes it before any downstream retrieval (along with NULL/missing rows).
    for name, params in transport.calls:
        if name != "query":
            assert set(params["objectIds"].split(",")) <= {identity[1] for identity in identities}
    for p in result.portfolios:
        records = [r for r in p.records if r.semantic_type == "measurement@ztf:lasair"]
        assert {r.get("time.mjd") for r in records} == {59000.0, 59015.0}
        classes = [r for r in p.records if r.semantic_type == "classification@sherlock:lasair"]
        assert classes and all(r.get("best.class") == label and r.get("best.score") == 2
                               and r.get("best.probability") is None for r in classes)
    # A complete object-only scan followed by object-context retrieval has the
    # same surviving identities, including the same NULL/absent/case behavior.
    local_transport, local_registry, local_executor = sherlock_replay(monkeypatch, label)
    local = f'objects from ztf via lasair\nlast within 10d\nwith classification from sherlock via lasair\nfilter {reference} = "{label}"\nwith lightcurve via lasair\n'
    local_result = execute_dsl(local, graph=graph, registry=local_registry, executor=local_executor, reference_time=NOW, continue_from=None)
    assert {summary_object_identity(p) for p in local_result.portfolios} == identities
    assert all(p["tables"] == "objects" for name, p in local_transport.calls if name == "query")


@pytest.mark.parametrize("mode", [None, "first", "last", "detection"])
def test_join_plan_keeps_conjunction_qualifiers_serialization_and_selection_order(graph, monkeypatch, mode):
    transport, registry, executor = sherlock_replay(monkeypatch)
    context = "" if mode is None else f'{mode + " " if mode != "detection" else ""}within 10d\n'
    source = ('objects from ztf via lasair\n' + context + 'latest 1\n'
              'where classification@sherlock:lasair.best.class = "AGN" and summary.detection_count >= 5\n'
              'with lightcurve via lasair\n')
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    step = validation.compilation.workflow.steps[0]
    plan = EndpointPlan.model_validate_json(plan_step(step, graph)[0].model_dump_json())
    assert plan.predicate_realization.residual == step.predicate
    assert "objects.ncand >= 5" in plan.predicate_realization.params["conditions"]
    bound = bind_endpoint(step, plan, registry, reference_time=NOW)
    assert bound.params["conditions"].count(" ORDER BY ") == 1
    result = execute_dsl(source, graph=graph, registry=registry, executor=executor, reference_time=NOW, continue_from=None)
    # First/detection membership does not bound an object's last detection.
    expected = "ZTF20bbbbbbb" if mode == "last" else "ZTF20ggggggg"
    assert {summary_object_identity(p)[1] for p in result.portfolios} == {expected}
    assert all(p["conditions"].endswith("ORDER BY objects.objectId") for name, p in transport.calls if name == "query")
    assert len([1 for name, p in transport.calls if name == "query"]) >= 2


@pytest.mark.parametrize("predicate", [
    None, comparison(),
    ComparisonPredicate(left=SemanticReference(semantic_type="classification", field_path="best.class"), operator="!=", right=PredicateLiteral(value="AGN")),
    ComparisonPredicate(left=SemanticReference(semantic_type="classification", field_path="best.class"), operator="=", right=PredicateLiteral(value="agn")),
])
def test_summary_search_never_borrows_a_sherlock_inner_join(graph, predicate):
    if predicate is None or predicate == comparison():
        plans = plan_step(search(predicate=predicate, time_context=TimeContext(mode="last", window=timedelta(days=10), relative_to="now")), graph)
        assert plans[0].request_params["tables"] == "objects"
    else:
        with pytest.raises(PlanningDeferredError):
            plan_step(search(predicate=predicate), graph)


@pytest.mark.parametrize("value", ["NULL", "SNII", "agn", 'AGN" OR 1=1', "AGN;", "AGN\\", True, 1])
def test_unsupported_or_unsafe_sherlock_literals_defer_before_io(graph, value):
    predicate = ComparisonPredicate(left=SemanticReference(semantic_type="classification", field_path="best.class"),
                                    operator="=", right=PredicateLiteral(value=value))
    with pytest.raises(PlanningDeferredError):
        plan_step(search(predicate=predicate), graph)


@pytest.mark.parametrize("failure,kwargs,message", [
    ("policy", {"max_pages": 1}, "max_auto_pages"),
    ("provider", {"error": True}, "JSON array"),
])
def test_join_coverage_failures_never_become_empty_success(graph, monkeypatch, failure, kwargs, message):
    transport, registry, executor = sherlock_replay(monkeypatch, **kwargs)
    with pytest.raises(WorkflowExecutionError, match=message):
        execute_dsl('objects from ztf via lasair\nwhere classification.best.class = "AGN"\nwith lightcurve via lasair\n',
                    graph=graph, registry=registry, executor=executor, continue_from=None)
    assert all(name == "query" for name, _ in transport.calls)


def test_join_residual_removes_wrong_missing_and_null_classes_before_retrieval(graph, monkeypatch):
    transport, registry, executor = sherlock_replay(monkeypatch, ignore_conditions=True)
    result = execute_dsl('objects from ztf via lasair\nwhere classification.best.class = "AGN"\n',
                         graph=graph, registry=registry, executor=executor, continue_from=None)
    expected = {"ZTF20aaaaaaa", "ZTF20bbbbbbb", "ZTF20ggggggg", "ZTF20hhhhhhh"}
    assert {summary_object_identity(p)[1] for p in result.portfolios} == expected
    assert [p["offset"] for name, p in transport.calls if name == "query"] == [0, 2, 4, 6]
    assert all(set(p["objectIds"].split(",")) <= expected for name, p in transport.calls if name != "query")


def test_join_continuation_retains_original_population_without_requery(graph, monkeypatch):
    transport, registry, executor = sherlock_replay(monkeypatch)
    first = execute_dsl('objects from ztf via lasair\nlast within 10d\nwhere classification.best.class = "AGN"\n',
                        graph=graph, registry=registry, executor=executor, reference_time=NOW, continue_from=None)
    snapshot = deepcopy(first.to_dict())
    count = len(transport.calls)
    second = execute_dsl('with lightcurve via lasair\n', graph=graph, registry=registry, executor=executor,
                         reference_time=NOW + timedelta(days=99), continue_from=first)
    assert all(name == "lightcurves" for name, _ in transport.calls[count:])
    assert first.to_dict() == snapshot
    assert second.staged.bindings[0].reference_time == NOW
    assert {summary_object_identity(p) for p in second.portfolios} == {summary_object_identity(p) for p in first.portfolios}


@pytest.mark.parametrize("qualifiers", [{"producer": "fink"}, {"channel": "fink"}, {"producer": "tns"}])
def test_join_cannot_relabel_another_producer_or_channel(graph, qualifiers):
    predicate = ComparisonPredicate(left=SemanticReference(semantic_type="classification", field_path="best.class", **qualifiers),
                                    operator="=", right=PredicateLiteral(value="AGN"))
    with pytest.raises(PlanningDeferredError):
        plan_step(search(predicate=predicate), graph)


@pytest.mark.parametrize("shape", ["or", "not", "score", "partial", "different_assertion"])
def test_join_does_not_hide_untranslated_conditions_behind_a_time_window(graph, shape):
    classification = ComparisonPredicate(left=SemanticReference(semantic_type="classification", field_path="best.class"),
                                         operator="=", right=PredicateLiteral(value="AGN"))
    if shape == "or":
        predicate = BooleanPredicate(operator="or", operands=(classification, comparison("detection_count")))
    elif shape == "not":
        predicate = NotPredicate(operand=classification)
    elif shape == "score":
        predicate = conjunction(classification, ComparisonPredicate(left=SemanticReference(semantic_type="classification", field_path="best.score"),
                                                                   operator=">=", right=PredicateLiteral(value=2)))
    elif shape == "partial":
        predicate = conjunction(classification, comparison("position.ra"))
    else:
        predicate = conjunction(classification, ComparisonPredicate(left=SemanticReference(semantic_type="classification", field_path="best.class", producer="tns"),
                                                                   operator="=", right=PredicateLiteral(value="SN")))
    with pytest.raises(PlanningDeferredError):
        plan_step(search(predicate=predicate, time_context=TimeContext(mode="last", window=timedelta(days=10), relative_to="now")), graph)


@pytest.mark.parametrize("change,message", [
    ("nonunique", "unique matching object key"), ("key", "unique matching object key"),
    ("identifier", "unique matching object key"), ("tables", "constant mapped projection"),
    ("projection", "constant mapped projection"), ("pagination", "automatic limit/offset"),
    ("exact", "explicit residual recheck"), ("operator", "safe label"),
    ("unsafe_domain", "safe label"), ("empty_domain", "safe label"),
    ("domain_type", "safe label"), ("subtraction", "output mapping transform"),
])
def test_invalid_sherlock_join_declarations_fail_at_loading(tmp_path, change, message):
    root = tmp_path / "providers"
    destination = root / "lasair/ztf"
    shutil.copytree(PROVIDERS_ROOT / "lasair/ztf", destination)
    path = destination / "capabilities.yaml"
    document = yaml.safe_load(path.read_text())
    call = next(item["calls"][0] for item in document["recipes"]["semantic_search"] if "sql_join" in item["calls"][0])
    binding = document["predicate_bindings"]["query"][-1]
    if change == "nonunique":
        call["sql_join"]["right_unique"] = False
    elif change == "key":
        call["sql_join"]["right"] = "sherlock_classifications.sourceId"
    elif change == "identifier":
        call["sql_join"]["right"] = "sherlock_classifications.objectId; DROP TABLE objects"
    elif change == "tables":
        call["params"]["tables"]["value"] += ",annotations"
    elif change == "projection":
        call["params"]["selected"]["value"] = PROJECTION
    elif change == "pagination":
        call["params"]["offset"] = {"value": 0}
    elif change == "exact":
        binding["exact"] = True
    elif change == "operator":
        binding["operator"] = ">="
    elif change == "unsafe_domain":
        binding["values"] = ['AGN" OR 1=1']
    elif change == "empty_domain":
        binding["values"] = []
    elif change == "domain_type":
        binding["values"] = "AGN"
    else:
        binding["sql"]["subtract"] = 1
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    with pytest.raises(CapabilityGraphError, match=message):
        build_capability_graph(root)


@pytest.mark.parametrize("value", ['AGN"', "AGN'", "AGN\\", "AGN;", "AGN\nOR", "AGN--", "AGN/*", 1, True, None])
def test_symbolic_sql_does_not_escape_or_interpolate_unadmitted_text(value):
    with pytest.raises(ValueError, match="safe label"):
        enum_comparison("sherlock_classifications.classification", "=", value, values=SHERLOCK_LABELS)


@pytest.mark.parametrize("contexts", [[], [{"objectId": "ZTF20aaaaaaa", "classification": None,
                                          "classificationReliability": 2, "description": "Missing class"}]])
def test_complete_empty_join_is_distinct_from_failed_coverage(graph, monkeypatch, contexts):
    transport, registry, executor = sherlock_replay(monkeypatch)
    transport.contexts = contexts
    result = execute_dsl('objects from ztf via lasair\nwhere classification.best.class = "AGN"\nwith lightcurve via lasair\n',
                         graph=graph, registry=registry, executor=executor, continue_from=None)
    assert result.portfolios == ()
    assert [name for name, _ in transport.calls] == ["query"]


@pytest.mark.parametrize("tail", [
    'where classification@sherlock:lasair.best.class = "AGN"\nlatest 1\n',
    'latest 1\nwith classification from sherlock via lasair where best.class = "AGN"\n',
    'with classification from sherlock via lasair where best.class = "AGN"\nlatest 1\n',
])
def test_native_join_preserves_scoped_class_conditions_and_latest_clause_order(graph, monkeypatch, tail):
    transport, registry, executor = sherlock_replay(monkeypatch)
    source = 'objects from ztf via lasair\nlast within 10d\n' + tail + 'with lightcurve via lasair\n'
    result = execute_dsl(source, graph=graph, registry=registry, executor=executor, reference_time=NOW, continue_from=None)
    assert {summary_object_identity(p)[1] for p in result.portfolios} == {"ZTF20bbbbbbb"}
    assert [p["offset"] for name, p in transport.calls if name == "query"] == [0, 2]
    assert all(p["tables"] == "objects,sherlock_classifications" for name, p in transport.calls if name == "query")
    assert all(p["objectIds"] == "ZTF20bbbbbbb" for name, p in transport.calls if name != "query")
