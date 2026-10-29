"""Synthetic SQL window declarations; production provider activation is separate.

SQLite independently evaluates compiled predicates and physical date conditions.
Detection-mode SQL is deliberately only a safe overlap prefilter in this file.
"""

from datetime import datetime, timedelta, timezone
import shutil
import sqlite3

import pytest
import yaml

from alertissimo.api import validate_dsl
from alertissimo.data_layer.execution import EndpointRegistry
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.runtime.capability_graph import CapabilityGraphError, build_capability_graph
from alertissimo.data_layer.transforms.sql import conjoin_ordered_conditions
from alertissimo.orchestration.binding import ParameterBindingError, UnsupportedParameterBindingError, bind_endpoint
from alertissimo.orchestration.ir import (
    BooleanPredicate, ComparisonPredicate, ConeSearchStep, PredicateLiteral, SemanticReference,
    SemanticSearchStep, Source, TimeContext,
)
from alertissimo.orchestration.planner import PlanningDeferredError, plan_step
from alertissimo.orchestration.runtime import EndpointPlan


NOW = datetime(2020, 6, 20, tzinfo=timezone.utc)  # UTC MJD 59020
ADAPTER = "alertissimo.data_layer.transforms.sql:time_window_condition"
OPTIONS = {"first_column": "objects.jdmin", "last_column": "objects.jdmax",
           "subtract": 2400000.5, "order_by": "objects.objectId"}
SOURCES = [Source(broker="lasair", origin="ztf")]
ROWS = [
    ("A", 7, 2459000.5, 2459030.5), ("B", 8, 2459000.5, 2459090.5),
    ("C", 3, 2459011.5, 2459050.5), ("D", 10, 2458990.5, 2459015.5),
    ("future", 9, 2459021.5, 2459060.5), ("old", 9, 2458980.5, 2459009.5),
]


def contract(tmp_path, mode="last"):
    root = tmp_path / "providers"
    dest = root / "lasair/ztf"
    shutil.copytree(PROVIDERS_ROOT / "lasair/ztf", dest)
    endpoints_path, recipes_path = dest / "endpoints.yaml", dest / "capabilities.yaml"
    endpoints, recipes = yaml.safe_load(endpoints_path.read_text()), yaml.safe_load(recipes_path.read_text())
    endpoints["endpoints"]["query"]["params"]["conditions"]["binding"]["time_context"] = {
        "adapter": ADAPTER, "adapter_options": OPTIONS,
    }
    recipe = recipes["recipes"]["semantic_search"][0]
    recipe["calls"][0]["params"]["conditions"] = {"from": "step.time_context"}
    if mode == "detection":
        recipe["calls"].append({"endpoint": "lightcurves", "params": {
            "objectIds": {"from": {"call": 0, "path": "summary.identity.object_id"}},
        }})
    recipe["time_selection"] = {
        "mode": mode, "method": "material" if mode == "detection" else "native",
        "call": 1 if mode == "detection" else 0,
        "payload": "lightcurve_candidates" if mode == "detection" else "query",
        "complete": True, "time_scale": "utc",
    }
    endpoints_path.write_text(yaml.safe_dump(endpoints, sort_keys=False))
    recipes_path.write_text(yaml.safe_dump(recipes, sort_keys=False))
    return root, dest


def search(mode="last", predicate=None, context=None):
    return SemanticSearchStep(sources=SOURCES, semantic_type="summary", predicate=predicate,
                              time_context=context or TimeContext(mode=mode, window=timedelta(days=10), relative_to="now"))


def count_predicate(operator=">=", value=5):
    return ComparisonPredicate(left=SemanticReference(semantic_type="summary", field_path="detection_count"),
                               operator=operator, right=PredicateLiteral(value=value))


def select_ids(conditions):
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE objects(objectId TEXT PRIMARY KEY, ncand INTEGER, jdmin REAL, jdmax REAL)")
        db.executemany("INSERT INTO objects VALUES (?,?,?,?)", ROWS)
        return [row[0] for row in db.execute("SELECT objectId FROM objects WHERE " + conditions)]


@pytest.mark.parametrize("mode,unfiltered,filtered", [
    ("detection", ["A", "B", "C", "D"], ["A", "B", "D"]),
    ("first", ["C"], []), ("last", ["D"], ["D"]),
])
@pytest.mark.parametrize("with_predicate", [False, True])
def test_whole_window_and_numeric_predicate_form_one_ordered_condition(tmp_path, mode, unfiltered, filtered, with_predicate):
    root, _ = contract(tmp_path, mode)
    graph = build_capability_graph(root)
    step = search(mode, count_predicate() if with_predicate else None)
    plans = plan_step(step, graph)
    plan = EndpointPlan.model_validate_json(plans[0].model_dump_json())
    assert plan.parameter_sources["conditions"] == ("time_context",)
    assert step.time_context.start_time is None and step.time_context.window == timedelta(days=10)
    assert (plan.predicate_realization is not None) == with_predicate
    if with_predicate:
        assert plan.predicate_realization.residual == step.predicate
    call = bind_endpoint(step, plan, EndpointRegistry(root), reference_time=NOW)
    sql = call.params["conditions"]
    assert sql.count(" ORDER BY ") == 1 and sql.endswith("ORDER BY objects.objectId")
    assert select_ids(sql) == (filtered if with_predicate else unfiltered)
    # B has observations on both sides of the interval but no proven inside
    # witness here. SQL overlap must retain it for the separate history check.
    if mode == "detection":
        assert "B" in select_ids(sql)
        assert plan.time_selection.evidence_plan_index == 1
    assert call.endpoint_spec.params["conditions"]["bind"] == "target_id"


def test_absolute_and_relative_windows_share_the_same_utc_bounds(tmp_path):
    root, _ = contract(tmp_path)
    graph, registry = build_capability_graph(root), EndpointRegistry(root)
    relative = search()
    absolute = search(context=TimeContext(mode="last", start_time="2020-06-10T02:00:00+02:00",
                                         end_time="2020-06-20T02:00:00+02:00"))
    relative_plan, = plan_step(relative, graph)
    absolute_plan, = plan_step(absolute, graph)
    assert bind_endpoint(relative, relative_plan, registry, reference_time=NOW).params == bind_endpoint(
        absolute, absolute_plan, registry, reference_time=NOW + timedelta(days=99)).params


def test_legacy_candidate_membership_uses_the_original_id_encoder(tmp_path):
    root, _ = contract(tmp_path)
    step = ConeSearchStep(sources=SOURCES, semantic_type="summary", ra=120, dec=-6, radius=5)
    plans = plan_step(step, build_capability_graph(root))
    assert plans[1].parameter_sources["conditions"] == "target_id"
    call = bind_endpoint(step, plans[1], EndpointRegistry(root), runtime_values={"target_id": ("ZTF20acpwljl",)})
    assert call.params["conditions"] == 'objects.objectId IN ("ZTF20acpwljl")'
    assert call.params["limit"] == 100 and call.params["offset"] == 0


def test_validation_and_planning_do_not_sample_a_clock(tmp_path, monkeypatch):
    root, _ = contract(tmp_path)
    class NoClock:
        @classmethod
        def now(cls, *args, **kwargs):
            raise AssertionError("planning sampled a clock")
    monkeypatch.setattr("alertissimo.orchestration.binding.binder.datetime", NoClock)
    result = validate_dsl("objects from ztf via lasair\nlast within 10d\n", graph=build_capability_graph(root), continue_from=None)
    assert result.is_runnable, result.lowering_error
    assert result.compilation.workflow.steps[0].time_context.window == timedelta(days=10)


@pytest.mark.parametrize("operator,value", [("!=", 5), (">=", "5"), (">=", "0; DROP TABLE objects")])
def test_a_window_does_not_admit_untranslated_sql_predicates(tmp_path, operator, value):
    root, _ = contract(tmp_path)
    with pytest.raises(PlanningDeferredError, match="eligible predicate assignment"):
        plan_step(search(predicate=count_predicate(operator, value)), build_capability_graph(root))


@pytest.mark.parametrize("operator", ["and", "or"])
def test_a_window_does_not_hide_an_untranslated_boolean_operand(tmp_path, operator):
    root, _ = contract(tmp_path)
    unmapped = ComparisonPredicate(left=SemanticReference(semantic_type="summary", field_path="position.ra"),
                                   operator=">=", right=PredicateLiteral(value=120))
    predicate = BooleanPredicate(operator=operator, operands=(count_predicate(), unmapped))
    with pytest.raises(PlanningDeferredError, match="eligible predicate assignment"):
        plan_step(search(predicate=predicate), build_capability_graph(root))


def test_runtime_values_cannot_replace_the_compiled_time_context(tmp_path):
    root, _ = contract(tmp_path)
    step = search(predicate=count_predicate())
    plan, = plan_step(step, build_capability_graph(root))
    for role in ("time_context", "semantic_predicate"):
        with pytest.raises(UnsupportedParameterBindingError):
            bind_endpoint(step, plan, EndpointRegistry(root), runtime_values={role: "arbitrary text"}, reference_time=NOW)
    realization = plan.predicate_realization.model_copy(update={"params": {"conditions": "objects.ncand >= 5 ORDER BY objects.ncand"}})
    changed = plan.model_copy(update={"predicate_realization": realization})
    with pytest.raises(ParameterBindingError, match="orderings conflict"):
        bind_endpoint(step, changed, EndpointRegistry(root), reference_time=NOW)


@pytest.mark.parametrize("change", ["column", "order", "subtract", "adapter", "null", "projection", "constant", "proof", "binding"])
def test_invalid_time_encoding_claims_fail_at_registry_loading(tmp_path, change):
    root, dest = contract(tmp_path)
    endpoint_path, recipe_path = dest / "endpoints.yaml", dest / "capabilities.yaml"
    endpoints, recipes = yaml.safe_load(endpoint_path.read_text()), yaml.safe_load(recipe_path.read_text())
    declaration = endpoints["endpoints"]["query"]["params"]["conditions"]["binding"]
    alternate = declaration["time_context"]
    recipe = recipes["recipes"]["semantic_search"][0]
    if change == "column":
        alternate["adapter_options"]["last_column"] = "objects.ramean"
    elif change == "order":
        alternate["adapter_options"]["order_by"] = "objects.ncand"
    elif change == "subtract":
        alternate["adapter_options"]["subtract"] = 0
    elif change == "adapter":
        alternate["adapter"] = "unregistered:callable"
    elif change == "null":
        declaration["time_context"] = None
    elif change == "projection":
        recipe["calls"][0]["params"]["selected"] = {"value": "objects.objectId"}
    elif change == "constant":
        recipe["calls"][0]["params"]["conditions"] = {"value": "1=1"}
    elif change == "proof":
        recipe.pop("time_selection")
    else:
        recipes["predicate_bindings"]["query"] = [item for item in recipes["predicate_bindings"]["query"]
                                                   if not (item["path"] == "summary.time.last_mjd" and item["operator"] == "<=")]
    endpoint_path.write_text(yaml.safe_dump(endpoints, sort_keys=False))
    recipe_path.write_text(yaml.safe_dump(recipes, sort_keys=False))
    with pytest.raises(CapabilityGraphError):
        build_capability_graph(root)


@pytest.mark.parametrize("left,right", [
    ("x > 1", "y < 2 ORDER BY objects.objectId"),
    ("x > 1 ORDER BY objects.objectId", "y < 2 ORDER BY objects.jdmin"),
    ("x > 1 ORDER BY objects.objectId", "y < 2 ORDER BY objects.objectId; DROP TABLE objects"),
])
def test_sql_composition_rejects_missing_or_incompatible_ordering(left, right):
    with pytest.raises(ValueError):
        conjoin_ordered_conditions(left, right)


def test_this_branch_does_not_activate_production_lasair_time_windows():
    graph = build_capability_graph()
    for prefix in ("", "first ", "last "):
        result = validate_dsl(f"objects from ztf via lasair\n{prefix}within 7d\n", graph=graph, continue_from=None)
        assert not result.is_runnable
