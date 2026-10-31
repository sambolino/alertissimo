"""Fink class/time discovery through the public facade; recorded and synthetic replays.

latests.json is the immutable class-endpoint capture. The SN regression selects
unchanged alert rows from objects_core.json to simulate the same class response
shape; it is not claimed to be a new captured latests response. For multi-object
binding tests, the transport replays selected latests rows as object responses.
All transport routing is a fixture: no HTTP call or upstream package is used.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil

import pytest
import yaml

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor, TransportResult
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.runtime.capability_graph import CapabilityGraphError, build_capability_graph
from alertissimo.dsl import SurfaceLoweringError
from alertissimo.orchestration.binding import bind_endpoint
from alertissimo.orchestration.ir import ComparisonPredicate, PredicateLiteral, SearchSelection, SemanticReference, TimeContext
from alertissimo.orchestration.normalization import normalize_workflow_execution, summary_object_identity
from alertissimo.orchestration.normalization.predicate import evaluate_portfolio_predicate
from alertissimo.orchestration.planner import PlanningDeferredError, plan_step, realize_predicate
from alertissimo.orchestration.runtime import EndpointPlan, WorkflowExecutionError


FIXTURES = Path(__file__).parent / "fixtures/fink/ztf"
NOW = datetime(2021, 11, 25, tzinfo=timezone.utc)
SN_NOW = datetime(2021, 7, 2, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def program(label="SN candidate", reference="classification.best.class"):
    return f'objects from ztf via fink\nwithin 7d\nwhere {reference} = "{label}"\n'


def recorded(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class ReplayTransport:
    name = "fixture"

    def __init__(self, discovery, objects=None):
        self.discovery = discovery
        self.objects = discovery if objects is None else objects
        self.calls = []

    def execute(self, spec, params, headers=None):
        assert (spec.broker, spec.origin, spec.method) == ("fink", "ztf", "GET")
        assert params["output-format"] == "json"
        self.calls.append((spec.endpoint, dict(params)))
        if spec.endpoint == "latests":
            assert "columns" not in params and "trend" not in params
            payload = self.discovery
        else:
            assert spec.endpoint == "objects"
            ids = set(params["objectId"].split(","))
            payload = [row for row in self.objects if row["i:objectId"] in ids]
        return TransportResult(deepcopy(payload), method="GET", status_code=200, content_type="application/json")


def executor(transport):
    return RegistryEndpointExecutor(transports={"rest": transport})


def identities(portfolios):
    return {summary_object_identity(portfolio) for portfolio in portfolios}


def test_exact_required_query_validates_and_binds_without_sampling_a_clock(graph, monkeypatch):
    class NoClock:
        @staticmethod
        def now(*args):
            raise AssertionError("validation must not resolve relative time")

    with monkeypatch.context() as patch:
        patch.setattr("alertissimo.orchestration.binding.binder.datetime", NoClock)
        patch.setattr("alertissimo.orchestration.pipeline.datetime", NoClock)
        validation = validate_dsl(program(), graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    step = validation.compilation.workflow.steps[0]
    assert step.time_context.window == timedelta(days=7)
    plan, = plan_step(step, graph)
    plan = EndpointPlan.model_validate_json(plan.model_dump_json())
    assert plan.endpoint == "latests"
    assert plan.predicate_realization.params == {"class": "SN candidate"}
    assert plan.predicate_realization.residual == step.predicate
    bound = bind_endpoint(step, plan, EndpointRegistry(), reference_time=NOW)
    assert bound.params == {
        "class": "SN candidate", "startdate": "2021-11-17T21:00:00.000000Z",
        "stopdate": "2021-11-25T03:00:00.000000Z",
    }


@pytest.mark.parametrize("reference", ["classification.best.class", "classification@fink.best.class", "classification@fink:fink.best.class"])
def test_recorded_class_response_partitions_objects_and_rechecks_qualified_evidence(graph, reference):
    rows = recorded("latests.json")
    transport = ReplayTransport(rows)
    result = execute_dsl(program("Early SN Ia candidate", reference), graph=graph,
                         executor=executor(transport), continue_from=None, reference_time=NOW)
    assert identities(result.portfolios) == {("ztf", row["i:objectId"]) for row in rows}
    assert len(result.portfolios) == 7
    discovery = result.result.steps[0].portfolios
    assert sum(record.semantic_type == "measurement@ztf:fink" for p in discovery for record in p.records) == 10
    assert sum(endpoint == "latests" for endpoint, _ in transport.calls) == 1
    # General where clauses also emit the DSL's classification requirement.
    # Its fresh objects retrieval is distinct from the class-index discovery.
    expected_ids = {row["i:objectId"] for row in rows}
    assert all(set(params["objectId"].split(",")) == expected_ids
               for endpoint, params in transport.calls if endpoint == "objects")
    assert result.staged.bindings[0].reference_time == NOW
    offline = normalize_workflow_execution(result.staged.execution)
    assert identities(offline.steps[0].portfolios) == identities(result.portfolios)


def test_exact_sn_query_retrieves_all_measurements_after_candidate_selection(graph):
    rows = recorded("objects_core.json")
    # Synthetic class-response routing of unchanged authoritative alert rows.
    stop_jd = 2459397.5  # 2021-07-02T00:00:00 UTC
    discovery = [row for row in rows if stop_jd - 7 <= row["i:jd"] < stop_jd and row["v:classification"] == "SN candidate"]
    assert 0 < len(discovery) < len(rows)
    transport = ReplayTransport(discovery, objects=rows)
    source = program() + "with lightcurve via fink\nwith classification via fink\n"
    result = execute_dsl(source, graph=graph, executor=executor(transport), continue_from=None, reference_time=SN_NOW)
    assert identities(result.portfolios) == {("ztf", "ZTF21abfmbix")}
    assert transport.calls[0][1]["startdate"] == "2021-06-24T21:00:00.000000Z"
    assert transport.calls[0][1]["stopdate"] == "2021-07-02T03:00:00.000000Z"
    objects_calls = [params for endpoint, params in transport.calls if endpoint == "objects"]
    assert objects_calls and all(params["objectId"] == "ZTF21abfmbix" for params in objects_calls)
    # within selects candidates. It must not trim the subsequently fetched LC.
    object_executions = [execution for step in result.staged.execution.steps for execution in step.executions
                         if execution.execution_provenance.endpoint == "objects"]
    assert object_executions and all(execution.payload == rows for execution in object_executions)
    points = [point for p in result.portfolios for record in p.records
              if record.semantic_type == "lightcurve@ztf:fink" for point in record.fields["points"]]
    assert {point["identity.source_id"] for point in points} == {row["i:candid"] for row in rows}


@pytest.mark.parametrize("filter_step", [False, True])
def test_residual_selection_feeds_only_survivor_ids_to_downstream_retrieval(graph, filter_step):
    rows = recorded("latests.json")
    transport = ReplayTransport(rows)
    source = program("Early SN Ia candidate")
    condition = "measurement@ztf:fink.position.ra > 30"
    source = source + f"filter {condition}\n" if filter_step else source.rstrip() + f" and {condition}\n"
    # An explicit classification clause after selection avoids the DSL's
    # implicit retrieval being inserted ahead of the filter.
    result = execute_dsl(source + "with lightcurve via fink\nwith classification via fink\n", graph=graph,
                         executor=executor(transport), continue_from=None, reference_time=NOW)
    expected = {row["i:objectId"] for row in rows if row["i:ra"] > 30}
    assert identities(result.portfolios) == {("ztf", oid) for oid in expected}
    calls = [params for endpoint, params in transport.calls if endpoint == "objects"]
    assert calls and all(set(params["objectId"].split(",")) == expected for params in calls)


@pytest.mark.parametrize("kind", ["empty", "different-class", "missing-class", "saturated"])
def test_empty_or_unproven_populations_do_not_trigger_downstream_calls(graph, kind):
    rows = recorded("latests.json")
    if kind == "empty":
        rows = []
    elif kind == "different-class":
        rows = [{**row, "v:classification": "Unknown"} for row in rows]
    elif kind == "missing-class":
        rows = [{key: value for key, value in row.items() if key != "v:classification"} for row in rows]
    else:
        rows = rows * 10  # synthetic saturation counts alerts, not unique objects
    transport = ReplayTransport(rows)
    source = program("Early SN Ia candidate") + "with lightcurve via fink\n"
    if kind == "saturated":
        with pytest.raises(WorkflowExecutionError, match=r"incomplete result.*n=100"):
            execute_dsl(source, graph=graph, executor=executor(transport), continue_from=None, reference_time=NOW)
    else:
        result = execute_dsl(source, graph=graph, executor=executor(transport), continue_from=None, reference_time=NOW)
        assert result.portfolios == ()
    assert [endpoint for endpoint, _ in transport.calls] == ["latests"]


@pytest.mark.parametrize("condition", [
    None,
    'classification.best.class != "SN candidate"',
    'classification.best.class = "SLSN candidate"',
    'classification.best.class = "(TNS) SN Ia"',
    'classification.best.class = "(SIMBAD) QSO"',
    'classification@lc_classifier.best.class = "SN candidate"',
    'classification@fink:lasair.best.class = "SN candidate"',
    'classification.best.class = "SN candidate" or classification.best.class = "Early SN Ia candidate"',
    'classification.best.class = "SN candidate" and classification.best.class = "Early SN Ia candidate"',
    'not (classification.best.class = "SN candidate")',
])
def test_missing_or_ineligible_class_is_rejected_before_transport(graph, condition):
    source = "objects from ztf via fink\nwithin 7d\n"
    if condition:
        source += f"where {condition}\n"
    transport = ReplayTransport([])
    assert not validate_dsl(source, graph=graph, continue_from=None).is_runnable
    with pytest.raises(SurfaceLoweringError):
        execute_dsl(source, graph=graph, executor=executor(transport), continue_from=None)
    assert transport.calls == []


def test_absolute_windows_and_no_window_keep_physical_contract_defaults(graph):
    validation = validate_dsl(program(), graph=graph, continue_from=None)
    step = validation.compilation.workflow.steps[0]
    absolute = step.model_copy(update={"time_context": TimeContext(
        start_time="2021-11-18T02:00:00+02:00", end_time="2021-11-25T02:00:00+02:00")})
    call = bind_endpoint(absolute, plan_step(absolute, graph)[0], EndpointRegistry())
    assert call.params["startdate"] == "2021-11-17T21:00:00.000000Z"
    assert call.params["stopdate"] == "2021-11-25T03:00:00.000000Z"
    unbounded = step.model_copy(update={"time_context": None})
    call = bind_endpoint(unbounded, plan_step(unbounded, graph)[0], EndpointRegistry())
    assert call.params == {"class": "SN candidate"}
    physical = RegistryEndpointExecutor._validated_params(call.endpoint_spec, call.params)
    assert physical["startdate"] == "2019-11-01 00:00:00" and "stopdate" not in physical
    with pytest.raises(PlanningDeferredError, match="latest requires"):
        plan_step(step.model_copy(update={"selection": SearchSelection(latest=1)}), graph)
    with pytest.raises(PlanningDeferredError, match="criteria"):
        plan_step(step.model_copy(update={"criteria": {"trend": "rising"}}), graph)
    wrong_literal = step.predicate.model_copy(update={"right": PredicateLiteral(value=1)})
    with pytest.raises(PlanningDeferredError, match="admitted literal values"):
        plan_step(step.model_copy(update={"predicate": wrong_literal}), graph)


def test_fink_continuation_replays_the_original_window_and_fresh_search_resolves_again(graph):
    transport = ReplayTransport(recorded("latests.json"))
    endpoint_executor = executor(transport)
    first = execute_dsl(program("Early SN Ia candidate"), graph=graph, executor=endpoint_executor,
                        continue_from=None, reference_time=NOW)
    before = list(transport.calls)
    later = NOW + timedelta(days=1)
    second = execute_dsl("with lightcurve via fink", graph=graph, executor=endpoint_executor,
                         continue_from=first, reference_time=later)
    assert second.staged.bindings[0].reference_time == NOW
    assert transport.calls[:len(before)] == before
    assert [endpoint for endpoint, _ in transport.calls[len(before):]] == ["objects"]
    execute_dsl(program("Early SN Ia candidate"), graph=graph, executor=endpoint_executor,
                continue_from=None, reference_time=later)
    fresh_discovery = [params for endpoint, params in transport.calls if endpoint == "latests"]
    assert len(fresh_discovery) == 2
    assert fresh_discovery[-1]["stopdate"] == "2021-11-26T03:00:00.000000Z"


@pytest.mark.parametrize("producer", ["other", "{producer}"])
def test_fixed_producer_proof_cannot_be_inferred_from_mixed_or_dynamic_mappings(graph, producer):
    endpoint = next(item for item in graph.endpoints_for("fink", "ztf") if item.endpoint == "latests")
    original = next(field for field in graph.fields_for_endpoint("fink", "ztf", "latests")
                    if field.semantic_path == "classification@fink.best.class")
    extra = replace(original, semantic_record_type=f"classification@{producer}",
                    semantic_path=f"classification@{producer}.best.class")
    modified = replace(graph, field_mapping_capabilities=graph.field_mapping_capabilities + (extra,))
    predicate = ComparisonPredicate(operator="=", left=SemanticReference(
        semantic_type="classification", producer="fink", field_path="best.class"),
        right=PredicateLiteral(value="SN candidate"))
    result = realize_predicate(predicate, endpoint=endpoint, graph=modified)
    assert result.params == {} and result.residual == predicate


def test_implicit_channel_recheck_uses_the_records_own_execution(graph):
    transport = ReplayTransport(recorded("latests.json"))
    result = execute_dsl(program("Early SN Ia candidate"), graph=graph, executor=executor(transport),
                         continue_from=None, reference_time=NOW)
    portfolio = result.portfolios[0]
    predicate = ComparisonPredicate(operator="=", left=SemanticReference(
        semantic_type="classification", producer="fink", channel="fink", field_path="best.class"),
        right=PredicateLiteral(value="Early SN Ia candidate"))
    assert evaluate_portfolio_predicate(portfolio, predicate)
    # Another broker in the Portfolio cannot supply a record's omitted channel.
    changed = replace(portfolio, executions=tuple(replace(execution, broker="other") for execution in portfolio.executions))
    assert not evaluate_portfolio_predicate(changed, predicate)
    anonymous = replace(portfolio, records=tuple(replace(record, internal_source=None) for record in portfolio.records))
    assert not evaluate_portfolio_predicate(anonymous, predicate)


@pytest.mark.parametrize("key,value,message", [
    ("values", [], "non-empty list"), ("values", None, "non-empty list"),
    ("values", [{"class": "SN"}], "scalar literals"),
    ("values", [1], "physical type"), ("exact", "false", "exact must be boolean"),
])
def test_invalid_binding_domains_fail_during_registry_compilation(tmp_path, key, value, message):
    root = tmp_path / "providers"
    destination = root / "fink/ztf"
    shutil.copytree(PROVIDERS_ROOT / "fink/ztf", destination)
    path = destination / "capabilities.yaml"
    document = yaml.safe_load(path.read_text())
    document["predicate_bindings"]["latests"][0][key] = value
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    with pytest.raises(CapabilityGraphError, match=message):
        build_capability_graph(root)


def test_rubin_tag_search_does_not_inherit_ztf_class_equality(graph):
    assert graph.query_recipes(broker="fink", origin="lsst", op="semantic_search") == ()
    source = program().replace("from ztf", "from lsst")
    assert not validate_dsl(source, graph=graph, continue_from=None).is_runnable
