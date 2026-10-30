"""Explicit object-time discovery; no live client or broker calls.

Object rows are unchanged captures except the separately marked synthetic ZTF
classification regression. The fake client simulates native filters/pagination;
it does not establish live population completeness or historical alert coverage.
"""

from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest
import yaml

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import EndpointRegistry, ExecutionPolicy, RegistryEndpointExecutor
from alertissimo.data_layer.runtime.capability_graph import CapabilityGraphError, build_capability_graph
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.dsl import SurfaceLoweringError
from alertissimo.orchestration.binding import ParameterBindingError, UnsupportedParameterBindingError, bind_endpoint
from alertissimo.orchestration.ir import ComparisonPredicate, PredicateLiteral, SemanticReference, SemanticSearchStep, Source, TimeContext
from alertissimo.orchestration.normalization import summary_object_identity
from alertissimo.orchestration.planner import PlanningDeferredError, plan_step
from alertissimo.orchestration.runtime import EndpointPlan, PredicateRealization, WorkflowExecutionError


FIXTURES = Path(__file__).parent / "fixtures/alerce"


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def rows(origin):
    payload = json.loads((FIXTURES / origin / "query_objects.json").read_text())
    return payload["items"] if origin == "ztf" else payload


def lightcurve_sample():
    payload = json.loads((FIXTURES / "ztf/query_lightcurve.json").read_text())
    return {branch: values[:2] + values[-2:] if len(values) > 4 else values
            for branch, values in payload.items()}


def predicate(field="last_mjd", operator=">=", value=61200):
    return ComparisonPredicate(operator=operator, left=SemanticReference(
        semantic_type="summary", field_path=f"time.{field}"), right=PredicateLiteral(value=value))


def search(origin, **kwargs):
    return SemanticSearchStep(sources=[Source(broker="alerce", origin=origin)], semantic_type="summary", **kwargs)


class RecordedClient:
    def __init__(self, origin, data=None, *, ignore_class_filter=False):
        self.origin = origin
        self.data = rows(origin) if data is None else data
        self.calls = []
        self.ignore_class_filter = ignore_class_filter

    def query_objects(self, *, survey, format="json", firstmjd=None, lastmjd=None,
                      classifier=None, class_name=None, probability=None,
                      page=None, page_size=None, order_by=None, order_mode=None):
        assert survey == self.origin and format == "json"
        if survey == "ztf":
            assert probability is None
        params = {key: value for key, value in locals().items()
                  if key not in {"self"} and value is not None}
        self.calls.append(("query_objects", params))
        selected = deepcopy(self.data)
        for field, limits in (("firstmjd", firstmjd), ("lastmjd", lastmjd)):
            if limits is not None:
                assert isinstance(limits, list) and 1 <= len(limits) <= 2
                selected = [row for row in selected if row[field] >= limits[0]
                            and (len(limits) == 1 or row[field] <= limits[1])]
        if not self.ignore_class_filter:
            class_field, producer_field = ("class", "classifier") if survey == "ztf" else ("class_name", "classifier_name")
            if class_name is not None:
                selected = [row for row in selected if row.get(class_field) == class_name]
            if classifier is not None:
                selected = [row for row in selected if row.get(producer_field) == classifier]
            if probability is not None:
                selected = [row for row in selected if row["probability"] >= probability]
        if order_by is not None:
            selected.sort(key=lambda row: row[order_by], reverse=order_mode == "DESC")
        start = ((page or 1) - 1) * page_size
        batch = selected[start:start + page_size]
        if survey == "lsst":
            return batch
        has_next = start + page_size < len(selected)
        return {"items": batch, "has_next": has_next, "next": (page or 1) + 1 if has_next else None,
                "page": page or 1, "prev": None, "has_prev": (page or 1) > 1, "total": len(selected)}

    def query_lightcurve(self, oid, *, survey, format="json"):
        assert survey == "ztf" and oid == "ZTF18abbuksn" and format == "json"
        self.calls.append(("query_lightcurve", {"oid": oid}))
        return lightcurve_sample()

    def query_forced_photometry(self, oid, *, survey, format="json"):
        assert survey == "ztf" and oid == "ZTF18abbuksn" and format == "json"
        self.calls.append(("query_forced_photometry", {"oid": oid}))
        return json.loads((FIXTURES / "ztf/query_forced_photometry.json").read_text())[:2]


def install_client(monkeypatch, client, *, page_size=2, max_pages=8):
    monkeypatch.setitem(sys.modules, "alerce.core", SimpleNamespace(Alerce=lambda: client))
    return RegistryEndpointExecutor(policy=ExecutionPolicy(page_size, max_pages, Path("fixture-policy.yaml")))


@pytest.mark.parametrize("origin", ["ztf", "lsst"])
@pytest.mark.parametrize("field,param", [("first_mjd", "firstmjd"), ("last_mjd", "lastmjd")])
def test_minimum_stays_a_scalar_in_the_plan_and_becomes_an_array_only_at_binding(graph, origin, field, param):
    step = search(origin, predicate=predicate(field, value=61200.125))
    plan, = plan_step(step, graph)
    restored = EndpointPlan.model_validate_json(plan.model_dump_json())
    assert restored.predicate_realization.params == {param: 61200.125}
    call = bind_endpoint(step, restored, EndpointRegistry())
    assert call.params == {param: [61200.125]}
    assert call.endpoint_spec.params[param]["type"] == "array"
    assert call.endpoint_spec.fixed_params == {"survey": origin}
    assert "survey" not in call.params and "page_size" not in call.params


@pytest.mark.parametrize("origin", ["ztf", "lsst"])
def test_only_the_authored_inclusive_minimum_is_pushed_and_other_operators_remain_residual(graph, origin):
    for operator in ("=", "!=", ">", "<", "<="):
        condition = predicate(operator=operator)
        plan, = plan_step(search(origin, predicate=condition), graph)
        assert plan.predicate_realization.params == {}
        assert plan.predicate_realization.residual == condition


def test_recorded_ztf_time_range_prunes_before_global_latest_selection(graph, monkeypatch):
    client = RecordedClient("ztf")
    endpoint_executor = install_client(monkeypatch, client, page_size=1)
    source = "objects from ztf via alerce\nlatest 1\nwhere summary.time.last_mjd >= 61000 and summary.time.last_mjd <= 61250\n"
    result = execute_dsl(source, graph=graph, executor=endpoint_executor, continue_from=None)
    assert {summary_object_identity(portfolio) for portfolio in result.portfolios} == {("ztf", "ZTF17aaaaaak")}
    calls = [params for endpoint, params in client.calls if endpoint == "query_objects"]
    assert len(calls) == 3  # includes a row excluded by the residual upper bound
    assert all(params["lastmjd"] == [61000.0] and params["order_by"] == "lastmjd" for params in calls)
    plan, = result.run.steps[0].endpoint_plans
    assert plan.predicate_realization.residual.operator == "<="


def test_rubin_reported_mjd_residuals_preserve_two_classifier_rows_for_one_object(graph, monkeypatch):
    client = RecordedClient("lsst")
    endpoint_executor = install_client(monkeypatch, client, page_size=1)
    source = "objects from lsst via alerce\nwhere summary.time.first_mjd >= 61200 and summary.time.last_mjd <= 61240\n"
    result = execute_dsl(source, graph=graph, executor=endpoint_executor, continue_from=None)
    assert len(client.calls) == 3  # bare-list pagination probes the empty final page
    assert {summary_object_identity(p) for p in result.portfolios} == {("lsst", "170587117485817955")}
    classifications = [record for p in result.portfolios for record in p.records if record.semantic_type.startswith("classification@")]
    assert {record.fields["best.class"] for record in classifications} == {"SN", "AGN"}
    assert all(record.fields["time.last_mjd"] == 61235.41918367943
               for p in result.portfolios for record in p.records if record.semantic_type == "summary@lsst:alerce")


def test_ztf_class_and_model_are_pushed_while_probability_is_rechecked_locally(graph, monkeypatch):
    # Synthetic classification fields on unchanged recorded object statistics.
    data = [{**row, "classifier": "lc_classifier", "class": "SN", "probability": 0.95}
            for row in rows("ztf")]
    client = RecordedClient("ztf", data)
    source = ('objects from ztf via alerce\nwhere classification@lc_classifier.best.class = "SN" '
              'and classification@lc_classifier.best.probability >= 0.8 '
              'and summary.time.last_mjd >= 61000 and summary.time.last_mjd <= 61100\n'
              'with lightcurve via alerce\n')
    result = execute_dsl(source, graph=graph, executor=install_client(monkeypatch, client), continue_from=None)
    assert {summary_object_identity(p) for p in result.portfolios} == {("ztf", "ZTF18abbuksn")}
    calls = [params for endpoint, params in client.calls if endpoint == "query_objects"]
    assert calls and all(params["classifier"] == "lc_classifier" and params["class_name"] == "SN" for params in calls)
    assert all("probability" not in params for params in calls)
    assert any(endpoint == "query_lightcurve" for endpoint, _ in client.calls)
    # Time selection is object recency. It must not trim fetched measurements.
    expected = lightcurve_sample()
    fetched = [execution for step in result.staged.execution.steps for execution in step.executions
               if execution.execution_provenance.endpoint == "query_lightcurve"]
    assert fetched and all(execution.payload == expected for execution in fetched)
    points = [point for portfolio in result.portfolios for record in portfolio.records
              if record.semantic_type == "lightcurve@ztf:alerce" for point in record.fields["points"]]
    assert {row["mjd"] for row in expected["detections"]} <= {point["time.mjd"] for point in points}
    assert min(point["time.mjd"] for point in points) < 61000


def test_ztf_selector_does_not_manufacture_class_evidence_from_null_capture_fields(graph, monkeypatch):
    client = RecordedClient("ztf", ignore_class_filter=True)
    source = 'objects from ztf via alerce\nwhere classification@lc_classifier.best.class = "SN"\nwith lightcurve via alerce\n'
    result = execute_dsl(source, graph=graph, executor=install_client(monkeypatch, client), continue_from=None)
    assert result.portfolios == ()
    assert all(endpoint == "query_objects" for endpoint, _ in client.calls)


@pytest.mark.parametrize("origin", ["lsst"])
def test_rubin_within_stays_deferred_without_its_own_time_scale_contract(graph, origin):
    source = f"objects from {origin} via alerce\nwithin 7d\n"
    assert not validate_dsl(source, graph=graph, continue_from=None).is_runnable
    with pytest.raises(PlanningDeferredError, match="time_context"):
        plan_step(search(origin, time_context=TimeContext(window=timedelta(days=7), relative_to="now")), graph)


def test_unsupported_class_operator_remains_a_local_residual(graph):
    condition = ComparisonPredicate(operator="!=", left=SemanticReference(
        semantic_type="classification", producer="lc_classifier", field_path="best.class"),
        right=PredicateLiteral(value="SN"))
    plan, = plan_step(search("ztf", predicate=condition), graph)
    assert plan.predicate_realization.params == {} and plan.predicate_realization.residual == condition


def test_wrong_channel_classification_is_rejected_before_transport(graph, monkeypatch):
    condition = ComparisonPredicate(operator="=", left=SemanticReference(
        semantic_type="classification", producer="lc_classifier", channel="fink", field_path="best.class"),
        right=PredicateLiteral(value="SN"))
    with pytest.raises(PlanningDeferredError, match="classification@lc_classifier:fink.best.class"):
        plan_step(search("ztf", predicate=condition), graph)
    client = RecordedClient("ztf")
    # Public compilation rejects the unavailable classifier recipe before the
    # planner's residual-material guard is reached.
    with pytest.raises(SurfaceLoweringError, match="no classification recipe maps the requested classifier") as caught:
        execute_dsl(
            'objects from ztf via alerce\n'
            'where classification@lc_classifier:fink.best.class = "SN"\n',
            graph=graph, executor=install_client(monkeypatch, client), continue_from=None,
        )
    assert caught.value.code == "unsupported_capability"
    assert caught.value.clause_index == 0
    assert client.calls == []


def test_operational_pagination_limit_is_not_silent_search_truncation(graph, monkeypatch):
    client = RecordedClient("ztf")
    endpoint_executor = install_client(monkeypatch, client, page_size=1, max_pages=1)
    source = "objects from ztf via alerce\nwhere summary.time.last_mjd >= 61000\nwith lightcurve via alerce\n"
    with pytest.raises(WorkflowExecutionError, match="execution-policy limit"):
        execute_dsl(source, graph=graph, executor=endpoint_executor, continue_from=None)
    assert len(client.calls) == 1 and client.calls[0][0] == "query_objects"


@pytest.mark.parametrize("value", [True, "61200", float("inf")])
def test_malformed_numeric_literal_fails_at_binding_before_any_transport(graph, value):
    step = search("ztf", predicate=predicate())
    plan, = plan_step(step, graph)
    # Keep the required semantic evidence so this fixture reaches the binder's
    # numeric encoder, rather than failing the runtime model's content guard.
    malformed = plan.model_copy(update={"predicate_realization": PredicateRealization(
        pushdown=step.predicate, params={"lastmjd": value},
    )})
    with pytest.raises(ParameterBindingError, match="finite numeric literal"):
        bind_endpoint(step, malformed, EndpointRegistry())
    with pytest.raises(UnsupportedParameterBindingError, match="planned predicate realization"):
        bind_endpoint(step, plan, EndpointRegistry(), runtime_values={"semantic_predicate": value})


@pytest.mark.parametrize("change", ["adapter", "operator", "type"])
def test_invalid_predicate_encodings_fail_registry_compilation(tmp_path, change):
    root = tmp_path / "providers"
    destination = root / "alerce/ztf"
    shutil.copytree(PROVIDERS_ROOT / "alerce/ztf", destination)
    if change == "operator":
        path = destination / "capabilities.yaml"
        document = yaml.safe_load(path.read_text())
        document["predicate_bindings"]["query_objects"][-1]["operator"] = "<"
    else:
        path = destination / "endpoints.yaml"
        document = yaml.safe_load(path.read_text())
        declaration = document["endpoints"]["query_objects"]["params"]["lastmjd"]
        if change == "type":
            declaration["type"] = "number"
        else:
            declaration["binding"]["adapter"] = "unregistered:callable"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    with pytest.raises(CapabilityGraphError):
        build_capability_graph(root)
