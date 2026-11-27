"""Measurement acquisition through the facade, using captured offline responses."""

from copy import deepcopy
from dataclasses import replace
from itertools import count
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import (
    SurfaceLoweringError, compile_surface_fragment, lower_surface,
    parse_surface_fragment, parse_surface_script, validate_surface_capabilities,
)
from alertissimo.orchestration.ir import (
    GetForcedPhotometryStep, GetMeasurementStep, LookupStep, Source, TargetSelector, WorkflowIR,
)
from alertissimo.orchestration.normalization import summary_object_identity
from alertissimo.orchestration.binding import bind_workflow_run
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import (
    EndpointPlanRef, WorkflowExecutionError, WorkflowRun, execute_workflow_run,
)
from alertissimo.data_layer.execution import EndpointRegistry


FIXTURES = Path(__file__).parent / "fixtures"
PAIRS = [(broker, origin) for broker in ("alerce", "fink", "lasair", "antares")
         for origin in ("ztf", "lsst")]
ROUTES = {
    ("alerce", "ztf"): [("query_lightcurve", True), ("query_forced_photometry", False)],
    ("alerce", "lsst"): [("query_lightcurve", True), ("query_forced_photometry", False)],
    ("fink", "ztf"): [("objects", True)],
    ("fink", "lsst"): [("sources", True), ("fp", False)],
    ("lasair", "ztf"): [("lightcurves", True)],
    ("lasair", "lsst"): [("object", True)],
    ("antares", "ztf"): [("get_by_ztf_object_id", True)],
    ("antares", "lsst"): [("get_by_lsst_dia_object_id", True)],
}


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def fixture(broker, origin, filename):
    return json.loads((FIXTURES / broker / origin / filename).read_text(encoding="utf-8"))


class Executor:
    """No fallback transport: every physical call must have a fixture."""

    def __init__(self, broker, origin, *, summary_only=False, fail=None):
        self.broker, self.origin = broker, origin
        self.calls, self.sequence = [], count()
        self.fail = fail
        if broker == "alerce":
            summary = fixture(broker, origin, "query_object.json")
            self.object_id = str(summary["oid"])
            self.payloads = {endpoint: fixture(broker, origin, endpoint + ".json")
                             for endpoint in ("query_object", "query_lightcurve", "query_forced_photometry")}
        elif broker == "fink":
            if origin == "ztf":
                rows = fixture(broker, origin, "objects_withupperlim.json")
                self.object_id = rows[0]["i:objectId"]
                self.payloads = {"objects": fixture(broker, origin, "objects_core.json")}
                self.upperlim_rows = rows
            else:
                self.payloads = {endpoint: fixture(broker, origin, endpoint + ".json")
                                 for endpoint in ("objects", "sources", "fp")}
                self.object_id = str(self.payloads["objects"][0]["r:diaObjectId"])
        elif broker == "lasair":
            if origin == "ztf":
                summary = fixture(broker, origin, "object_ZTF23aamxeqf.json")
                self.object_id = summary["objectId"]
                self.payloads = {"object": summary, "objects": [deepcopy(summary)],
                                 "lightcurves": fixture(broker, origin, "lightcurves_ZTF23aamxeqf.json")}
                if summary_only:
                    # A valid sparse lookup; the later history response remains complete as captured.
                    self.payloads["object"] = {"objectId": self.object_id}
                    self.payloads["objects"] = [{"objectId": self.object_id}]
            else:
                summary = fixture(broker, origin, "object.json")
                self.object_id = str(summary["diaObjectId"])
                self.payloads = {"object": summary}
        else:
            endpoint = "get_by_ztf_object_id" if origin == "ztf" else "get_by_lsst_dia_object_id"
            summary = fixture(broker, origin, endpoint + ".json")
            summary["alerts"] = fixture(broker, origin, "alerts.json")
            self.object_id = (summary["properties"]["ztf_object_id"] if origin == "ztf"
                              else str(summary["alerts"][0]["properties"]["lsst_diaObject_diaObjectId"]))
            self.payloads = {endpoint: summary}

    @property
    def lookup(self):
        return f"object {self.object_id} from {self.origin} via {self.broker}\n"

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        assert (broker, origin) == (self.broker, self.origin)
        assert headers is None and endpoint in self.payloads
        params = deepcopy(dict(params or {}))
        self.calls.append((broker, origin, endpoint, params))
        if endpoint == self.fail:
            raise RuntimeError("controlled measurement acquisition failure")
        return ExecutionResult(
            payload=deepcopy(self.upperlim_rows if (broker, origin, endpoint) == ("fink", "ztf", "objects")
                             and params.get("withupperlim") is True else self.payloads[endpoint]),
            execution_provenance=InternalExecutionProvenance(
                internal_execution_id=InternalExecutionId(f"measurement:{next(self.sequence)}"),
                broker=broker, origin=origin, endpoint=endpoint, params=params,
            ),
        )


def measurements(result, broker, origin):
    return [record for portfolio in result.portfolios for record in portfolio.records
            if record.semantic_type == f"measurement@{origin}:{broker}"]


@pytest.mark.parametrize("broker,origin", PAIRS)
def test_measurement_is_a_distinct_step_with_a_declared_bound_recipe(graph, broker, origin):
    executor = Executor(broker, origin)
    source = executor.lookup + "with measurement"
    result = validate_dsl(source, graph=graph, continue_from=None)
    assert result.is_valid and result.is_runnable, result.lowering_error
    workflow = result.compilation.workflow
    assert workflow.dsl_version == 3
    assert [step.op for step in workflow.steps] == ["lookup", "get_measurement"]
    assert isinstance(workflow.steps[-1], GetMeasurementStep)
    assert WorkflowIR.model_validate_json(workflow.model_dump_json()) == workflow
    run = plan_workflow(workflow, graph)
    # Existing policy omits optional singular calls when the target population is
    # supplied later by a dependency. Required calls still fan out in the binder.
    expected = [entry for entry in ROUTES[broker, origin] if broker != "alerce" or entry[1]]
    assert [(plan.endpoint, plan.required) for plan in run.steps[-1].endpoint_plans] == expected
    assert all(plan.parameter_sources for plan in run.steps[-1].endpoint_plans)
    executed = execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    assert measurements(executed, broker, origin)
    assert len(executed.portfolios) == 1
    assert str(summary_object_identity(executed.portfolios[0])[1]) == executor.object_id
    assert WorkflowRun.model_validate_json(executed.run.model_dump_json()) == executed.run
    if (broker, origin) == ("fink", "ztf"):
        assert executor.calls[-1][3]["withupperlim"] is True
        assert any(any(key.endswith(".upper_limit") and value is True for key, value in row.fields.items())
                   for row in measurements(executed, broker, origin))


@pytest.mark.parametrize("broker", ["alerce", "lasair"])
def test_measurement_can_acquire_history_absent_from_the_lookup(graph, broker):
    executor = Executor(broker, "ztf", summary_only=True)
    plain = execute_dsl(executor.lookup, graph=graph, executor=executor, continue_from=None)
    assert not measurements(plain, broker, "ztf")
    before = plain.to_dict()
    enriched = execute_dsl("with measurement", graph=graph, executor=executor, continue_from=plain)
    rows = measurements(enriched, broker, "ztf")
    assert rows
    assert any(any(key.endswith(".upper_limit") and value is True for key, value in r.fields.items())
               for r in rows)
    assert any(any(key.endswith(".upper_limit") and value is False for key, value in r.fields.items())
               for r in rows)
    assert plain.to_dict() == before
    assert enriched.run.steps[:len(plain.run.steps)] == plain.run.steps
    assert enriched.workflow.steps[-1].op == "get_measurement"


@pytest.mark.parametrize("broker,origin", PAIRS)
def test_missing_measurement_recipe_names_the_provider_and_never_uses_legacy_outputs(graph, broker, origin):
    restricted = replace(graph, recipe_capabilities=tuple(
        recipe for recipe in graph.recipe_capabilities
        if (recipe.broker, recipe.origin, recipe.op) != (broker, origin, "get_measurement")
    ))
    executor = Executor(broker, origin)
    result = validate_dsl(executor.lookup + "with measurement", graph=restricted, continue_from=None)
    assert result.is_valid and not result.is_runnable
    assert broker in str(result.lowering_error)
    assert "get_measurement" in str(result.lowering_error)


@pytest.mark.parametrize("tail", [
    "where measurement.quality.real_bogus > 0.5\nwith measurement",
    "with measurement\nwhere measurement.quality.real_bogus > 0.5",
])
def test_incidental_reference_cannot_discharge_an_explicit_acquisition_requirement(graph, tail):
    restricted = replace(graph, recipe_capabilities=tuple(
        recipe for recipe in graph.recipe_capabilities if recipe.op != "get_measurement"
    ))
    executor = Executor("lasair", "ztf")
    surface = parse_surface_script(executor.lookup + tail)
    report = validate_surface_capabilities(surface, graph=restricted)
    assert not report.is_supported
    assert any("no get_measurement recipe" in check.reason for check in report.unsupported)


@pytest.mark.parametrize("broker,origin,endpoint", [
    ("alerce", "ztf", "query_forced_photometry"),
    ("alerce", "lsst", "query_forced_photometry"),
    ("fink", "lsst", "fp"),
])
def test_supplementary_forced_calls_stay_optional(graph, broker, origin, endpoint):
    executor = Executor(broker, origin, fail=endpoint)
    workflow = WorkflowIR(steps=[GetMeasurementStep(
        target=TargetSelector(ids=[executor.object_id], kind="object"),
        sources=[Source(broker=broker, origin=origin)],
    )])
    run = plan_workflow(workflow, graph)
    assert [(plan.endpoint, plan.required) for plan in run.steps[0].endpoint_plans] == ROUTES[broker, origin]
    result = execute_workflow_run(run, bind_workflow_run(run, EndpointRegistry()), executor)
    assert any(call[2] == endpoint for call in executor.calls)
    assert result.run.steps[-1].warnings


def test_collection_capable_optional_supplement_stays_optional_through_the_facade(graph):
    executor = Executor("fink", "lsst", fail="fp")
    result = execute_dsl(executor.lookup + "with measurement", graph=graph,
                         executor=executor, continue_from=None)
    assert measurements(result, "fink", "lsst")
    assert any(call[2] == "fp" for call in executor.calls)
    assert result.run.steps[-1].warnings


def test_required_measurement_call_failure_is_visible(graph):
    executor = Executor("lasair", "ztf", summary_only=True, fail="lightcurves")
    with pytest.raises(WorkflowExecutionError, match="controlled measurement acquisition failure"):
        execute_dsl(executor.lookup + "with measurement", graph=graph,
                    executor=executor, continue_from=None)


def test_measurement_broker_override_binds_the_selected_object_identity(graph):
    history = Executor("lasair", "ztf")
    calls = []

    class CrossBrokerExecutor:
        def execute(self, broker, origin, endpoint, params=None, headers=None):
            calls.append((broker, origin, endpoint, dict(params or {})))
            if broker == "alerce":
                assert (origin, endpoint) == ("ztf", "query_object")
                assert params["oid"] == history.object_id
                # Synthetic ALeRCE identity response for the selected captured ZTF object.
                return ExecutionResult(
                    payload={"oid": history.object_id, "meanra": 10.0, "meandec": 20.0},
                    execution_provenance=InternalExecutionProvenance(
                        InternalExecutionId("measurement:lookup"), broker, origin, endpoint, params=params,
                    ),
                )
            assert params["objectIds"] == history.object_id
            return history.execute(broker, origin, endpoint, params=params, headers=headers)

    source = f"object {history.object_id} from ztf via alerce\nwith measurement via lasair"
    result = execute_dsl(source, graph=graph, executor=CrossBrokerExecutor(), continue_from=None)
    assert len(measurements(result, "lasair", "ztf")) == 21
    assert [(b, e) for b, _, e, _ in calls] == [("alerce", "query_object"), ("lasair", "lightcurves")]


@pytest.mark.parametrize("collection", ["measurement@ztf:lasair", "lightcurve@ztf:lasair.points"])
def test_measurements_and_series_points_are_not_pooled(graph, collection):
    executor = Executor("lasair", "ztf", summary_only=True)
    source = executor.lookup + "with measurement\n"
    witnessed = execute_dsl(source + f"filter count({collection}) >= 21", graph=graph,
                            executor=executor, continue_from=None)
    assert len(witnessed.portfolios) == 1
    # One history call emits 21 measurements and 21 points. Neither count is 42.
    not_witnessed = execute_dsl(source + f"filter count({collection}) >= 42", graph=graph,
                                executor=Executor("lasair", "ztf", summary_only=True), continue_from=None)
    assert not_witnessed.portfolios == ()


def test_measurement_completeness_remains_open_and_later_filters_reuse_material(graph):
    executor = Executor("lasair", "ztf", summary_only=True)
    first = execute_dsl(executor.lookup + "with measurement", graph=graph,
                        executor=executor, continue_from=None)
    calls = deepcopy(executor.calls)
    selected = execute_dsl("filter count(measurement@ztf:lasair) >= 21", graph=graph,
                           executor=executor, continue_from=first)
    assert len(selected.portfolios) == 1
    unknown = execute_dsl("filter count(measurement@ztf:lasair) = 21", graph=graph,
                          executor=executor, continue_from=first)
    assert unknown.portfolios == ()
    assert executor.calls == calls


@pytest.mark.parametrize("tail", [
    "with measurement where photometry.g.upper_limit = false",
    "with measurement\nfilter count(measurement@ztf:lasair where photometry.g.upper_limit = false) >= 1",
])
def test_scoped_and_later_predicates_use_the_retrieved_measurements(graph, tail):
    executor = Executor("lasair", "ztf", summary_only=True)
    result = execute_dsl(executor.lookup + tail, graph=graph, executor=executor, continue_from=None)
    assert len(result.portfolios) == 1
    assert [step.op for step in result.workflow.steps] == ["lookup", "get_measurement", "filter"]
    assert [call[2] for call in executor.calls] == ["object", "lightcurves"]


def test_explicit_plural_measurement_retrieval_keeps_required_singular_fanout(graph):
    workflow = WorkflowIR(steps=[GetMeasurementStep(
        target=TargetSelector(ids=["A", "B"], kind="object"),
        sources=[Source(broker="alerce", origin="ztf")],
    )])
    run = plan_workflow(workflow, graph)
    assert [plan.endpoint for plan in run.steps[0].endpoint_plans] == ["query_lightcurve"]
    bindings = bind_workflow_run(run, EndpointRegistry())
    assert [call.params for call in bindings[0].bound_calls] == [{"oid": "A"}, {"oid": "B"}]


def test_incidental_measurement_predicates_do_not_add_a_history_step(graph):
    source = "object ZTF23aamxeqf from ztf via lasair\nwhere measurement.quality.real_bogus > 0.5"
    # Pure lowering isolates scheduling from capability eligibility.
    workflow = lower_surface(parse_surface_script(source), graph=graph).workflow
    assert [step.op for step in workflow.steps] == ["lookup", "filter"]
    executor = Executor("lasair", "ztf")
    executed = execute_dsl(executor.lookup, graph=graph, executor=executor, continue_from=None)
    assert len(measurements(executed, "lasair", "ztf")) == 21
    assert len(executor.calls) == 1


def test_old_qualified_scalar_where_does_not_require_a_new_measurement_recipe(graph):
    restricted = replace(graph, recipe_capabilities=tuple(
        recipe for recipe in graph.recipe_capabilities if recipe.op != "get_measurement"
    ))
    executor = Executor("lasair", "ztf")
    source = executor.lookup + "where measurement@ztf:lasair.quality.real_bogus > 0.5"
    validation = validate_dsl(source, graph=restricted, continue_from=None)
    assert validation.is_valid and validation.is_runnable, validation.lowering_error
    result = execute_dsl(source, graph=restricted, executor=executor, continue_from=None)
    assert len(result.portfolios) == 1
    assert len(executor.calls) == 1
    assert [step.op for step in result.workflow.steps] == ["lookup", "filter"]


@pytest.mark.parametrize("origin", ["ztf", "lsst"])
def test_existing_explicit_forced_retrieval_can_supply_the_measurement_supplement(graph, origin):
    target = TargetSelector(ids=["A"], kind="object")
    sources = [Source(broker="alerce", origin=origin)]
    workflow = WorkflowIR(steps=[GetForcedPhotometryStep(target=target, sources=sources),
                                 GetMeasurementStep(target=target, sources=sources)])
    run = plan_workflow(workflow, graph)
    assert run.steps[1].endpoint_plans[1].execution_reuse_from == EndpointPlanRef(step_index=0, plan_index=0)


@pytest.mark.parametrize("version", [1, 2])
def test_old_versions_refuse_new_operation_without_implicit_upgrade(graph, version):
    with pytest.raises(ValidationError, match="measurement retrieval requires dsl_version 3"):
        WorkflowIR(steps=[GetMeasurementStep()], dsl_version=version)
    legacy = WorkflowIR(steps=[LookupStep(target=TargetSelector(ids=["A"], kind="object"),
                                          sources=[Source(broker="alerce", origin="ztf")])], dsl_version=version)
    assert WorkflowIR.model_validate_json(legacy.model_dump_json()) == legacy
    with pytest.raises(SurfaceLoweringError, match="older continuation is not implicitly upgraded"):
        compile_surface_fragment(parse_surface_fragment("with measurement"), legacy, graph=graph)


def test_unversioned_measurement_ir_is_not_misread_as_legacy():
    with pytest.raises(ValidationError, match="measurement retrieval requires dsl_version 3"):
        WorkflowIR.model_validate({"steps": [{"op": "get_measurement"}]})


def test_version_three_is_refused_by_the_previous_runtime_version_guard(monkeypatch):
    from alertissimo.orchestration.ir import models

    encoded = WorkflowIR(steps=[GetMeasurementStep()]).model_dump_json()
    monkeypatch.setattr(models, "CURRENT_DSL_VERSION", 2)
    with pytest.raises(ValidationError, match="newer than supported version 2"):
        WorkflowIR.model_validate_json(encoded)
