"""Required product components use existing recipes and immutable evidence."""

from copy import deepcopy
from dataclasses import replace
from itertools import count
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance, InternalRecordId
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.data_layer.runtime.recipes import ConstantValueSource, RecipeParameter
from alertissimo.data_layer.semantic_model import SemanticPathModel
from alertissimo.dsl import lower_surface, parse_surface_script
from alertissimo.dsl.predicate_lowering import lower_expression_predicate
from alertissimo.orchestration.ir import (
    FilterStep, GetLightcurveStep, GetMeasurementStep, LookupStep, SemanticReference, Source, TargetSelector, WorkflowIR,
)
from alertissimo.orchestration.normalization.predicate import evaluate_portfolio_predicate_truth
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import WorkflowExecutionError, WorkflowRun
from alertissimo.orchestration.validation import validate_step_capabilities
from alertissimo.dsl.lowering import _require_referenced_components as require_referenced_components


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


class Executor:
    def __init__(self, broker="alerce", origin="ztf", *, empty=False, fail=False, malformed=False):
        self.broker, self.origin = broker, origin
        self.calls, self.sequence = [], count()
        self.fail = fail
        def read(name):
            return json.loads((FIXTURES / broker / origin / (name + ".json")).read_text())
        if broker == "alerce":
            self.payloads = {name: read(name) for name in ("query_object", "query_lightcurve", "query_forced_photometry")}
            self.object_id = str(self.payloads["query_object"]["oid"])
            self.forced_endpoint = "query_forced_photometry"
            bundle = self.payloads["query_lightcurve"]
            for key, rows in bundle.items():
                if isinstance(rows, list):
                    bundle[key] = [] if empty and key == "forced_photometry" else rows[:1]
        else:
            self.payloads = {name: read(name) for name in ("objects", "sources", "fp")}
            self.object_id = str(self.payloads["objects"][0]["r:diaObjectId"])
            self.payloads["sources"] = self.payloads["sources"][:1]
            self.forced_endpoint = "fp"
        self.payloads[self.forced_endpoint] = ([] if empty else self.payloads[self.forced_endpoint][:1])
        if malformed:
            self.payloads[self.forced_endpoint] = None

    @property
    def lookup(self):
        return f"object {self.object_id} from {self.origin} via {self.broker}\n"

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        assert (broker, origin) == (self.broker, self.origin) and endpoint in self.payloads
        params = deepcopy(dict(params or {}))
        self.calls.append((endpoint, params))
        if endpoint == self.forced_endpoint and self.fail:
            raise RuntimeError("required component failed")
        return ExecutionResult(
            payload=deepcopy(self.payloads[endpoint]),
            execution_provenance=InternalExecutionProvenance(
                InternalExecutionId(f"component:{next(self.sequence)}"), broker, origin, endpoint, params=params,
            ),
        )


def count_for(executor, relation=">= 1"):
    return f"count(lightcurve@{executor.origin}:{executor.broker}.forced_photometry_points) {relation}"


@pytest.mark.parametrize("broker,origin,product", [
    ("alerce", "ztf", "lightcurve.forced_photometry_points"),
    ("fink", "lsst", "lightcurve.forced_photometry_points"),
    ("alerce", "lsst", "measurement.forced_photometry"),
])
def test_explicit_component_promotes_all_own_producing_calls(graph, broker, origin, product):
    executor = Executor(broker, origin)
    result = validate_dsl(executor.lookup + "with " + product, graph=graph, continue_from=None)
    assert result.is_valid and result.is_runnable, result.lowering_error
    workflow = result.compilation.workflow
    step = workflow.steps[-1]
    assert step.required_components and all(isinstance(c, SemanticReference) for c in step.required_components)
    plans = plan_workflow(workflow, graph).steps[-1].endpoint_plans
    assert [plan.required for plan in plans] == [True, True]
    assert [plan.endpoint for plan in plans] == (["query_lightcurve", "query_forced_photometry"]
                                                if broker == "alerce" else ["sources", "fp"])
    executed = execute_dsl(executor.lookup + "with " + product, graph=graph, executor=executor, continue_from=None)
    assert len(executed.portfolios) == 1
    assert WorkflowRun.model_validate_json(executed.run.model_dump_json()) == executed.run
    assert WorkflowIR.model_validate_json(workflow.model_dump_json()) == workflow


@pytest.mark.parametrize("broker,origin", [("alerce", "ztf"), ("fink", "lsst")])
def test_required_component_failure_is_visible(graph, broker, origin):
    executor = Executor(broker, origin, fail=True)
    with pytest.raises(WorkflowExecutionError, match="required component failed"):
        execute_dsl(executor.lookup + "with lightcurve.forced_photometry_points", graph=graph,
                    executor=executor, continue_from=None)


@pytest.mark.parametrize("broker,origin", [("alerce", "ztf"), ("alerce", "lsst"), ("fink", "lsst")])
def test_empty_success_keeps_the_object_and_proves_only_the_empty_component(graph, broker, origin):
    executor = Executor(broker, origin, empty=True)
    source = executor.lookup + "with lightcurve.forced_photometry_points\n"
    first = execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    assert len(first.portfolios) == 1
    assert not any(record.fields.get("forced_photometry_points") for record in first.portfolios[0].records)
    calls, before = deepcopy(executor.calls), first.to_dict()
    zero = execute_dsl("filter " + count_for(executor, "= 0"), graph=graph, executor=executor, continue_from=first)
    assert len(zero.portfolios) == 1
    assert executor.calls == calls and first.to_dict() == before
    # The ordinary nonempty history still has an open upper bound.
    actual = sum(len(record.fields.get("points", ())) for record in first.portfolios[0].records)
    unknown = execute_dsl(f"filter count(lightcurve@{origin}:{broker}.points) = {actual}", graph=graph,
                          executor=executor, continue_from=first)
    assert unknown.portfolios == ()


@pytest.mark.parametrize("broker,origin", [("alerce", "ztf"), ("fink", "lsst")])
def test_same_program_empty_filter_agrees_with_continuation_and_final_normalization(graph, broker, origin):
    executor = Executor(broker, origin, empty=True)
    result = execute_dsl(executor.lookup + "with lightcurve\nfilter " + count_for(executor, "= 0"),
                         graph=graph, executor=executor, continue_from=None)
    assert len(result.portfolios) == 1
    assert all(plan.required for plan in result.run.steps[1].endpoint_plans)


@pytest.mark.parametrize("tail", [
    "with lightcurve\nfilter count(lightcurve@ztf:alerce.forced_photometry_points where time.mjd > 60000) >= 1",
    "with lightcurve where forced_photometry_points exists",
])
def test_references_strengthen_existing_retrieval_without_adding_a_step(graph, tail):
    executor = Executor()
    result = validate_dsl(executor.lookup + tail, graph=graph, continue_from=None)
    assert result.is_valid and result.is_runnable, result.lowering_error
    assert [step.op for step in result.compilation.workflow.steps] == ["lookup", "get_lightcurve", "filter"]
    assert all(plan.required for plan in plan_workflow(result.compilation.workflow, graph).steps[1].endpoint_plans)


@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize("selection", ["filter_count", "scoped_exists"])
def test_selection_and_retrieval_are_distinct(graph, empty, selection):
    executor = Executor(empty=empty)
    tail = ("with lightcurve\nfilter " + count_for(executor) if selection == "filter_count"
            else "with lightcurve where forced_photometry_points exists")
    result = execute_dsl(executor.lookup + tail, graph=graph, executor=executor, continue_from=None)
    assert len(result.portfolios) == (0 if empty else 1)
    assert [step.op for step in result.workflow.steps] == ["lookup", "get_lightcurve", "filter"]


@pytest.mark.parametrize("tail", [
    "filter count(lightcurve@ztf:alerce.forced_photometry_points) >= 1",
    "where count(lightcurve@ztf:alerce.forced_photometry_points) >= 1",
    "where lightcurve@ztf:alerce.forced_photometry_points exists",
    "where lightcurve.forced_photometry_points exists",
    "filter lightcurve@ztf:alerce.forced_photometry_points exists",
])
def test_no_parent_retrieval_still_names_item_4a(graph, tail):
    executor = Executor()
    source = executor.lookup + tail
    result = validate_dsl(source, graph=graph, continue_from=None)
    assert result.is_valid and not result.is_runnable
    assert "item 4a" in str(result.lowering_error)
    pure = lower_surface(parse_surface_script(source), graph=graph).workflow
    assert not any(isinstance(step, GetLightcurveStep) for step in pure.steps)


@pytest.mark.parametrize("clause", ["where", "filter"])
@pytest.mark.parametrize("empty", [False, True])
def test_qualified_component_exists_uses_an_existing_retrieval(graph, clause, empty):
    executor = Executor(empty=empty)
    source = (executor.lookup + "with lightcurve\n" + clause
              + " lightcurve@ztf:alerce.forced_photometry_points exists")
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_valid and validation.is_runnable, validation.lowering_error
    assert [step.op for step in validation.compilation.workflow.steps] == ["lookup", "get_lightcurve", "filter"]
    result = execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    assert len(result.portfolios) == (0 if empty else 1)
    assert [endpoint for endpoint, _ in executor.calls] == ["query_object", "query_lightcurve", "query_forced_photometry"]


def test_no_route_names_broker_and_does_not_borrow_other_operation_calls(graph):
    executor = Executor()
    source = executor.lookup + "with lightcurve.forced_photometry_points via antares"
    result = validate_dsl(source, graph=graph, continue_from=None)
    assert result.is_valid and not result.is_runnable
    assert "antares" in str(result.lowering_error)
    restricted = replace(graph, recipe_capabilities=tuple(
        replace(recipe, calls=recipe.calls[:1]) if (recipe.broker, recipe.origin, recipe.op) == ("alerce", "ztf", "get_lightcurve")
        else recipe for recipe in graph.recipe_capabilities
    ))
    assert restricted.query_recipes(broker="alerce", origin="ztf", op="get_forced_photometry")
    result = validate_dsl(executor.lookup + "with lightcurve.forced_photometry_points", graph=restricted, continue_from=None)
    assert result.is_valid and not result.is_runnable



def test_projected_out_component_is_not_guaranteed_by_its_mapping(graph):
    # The endpoint can map forced flux, but this recipe requests identity only.
    def project(recipe):
        if (recipe.broker, recipe.origin, recipe.op) != ("alerce", "ztf", "get_lightcurve"):
            return recipe
        return replace(recipe, calls=tuple(
            replace(call, params=call.params + (RecipeParameter("columns", ConstantValueSource("measurement_id")),))
            if call.endpoint == "query_forced_photometry" else call for call in recipe.calls
        ))
    projected = replace(graph, recipe_capabilities=tuple(project(r) for r in graph.recipe_capabilities),
                        endpoint_capabilities=tuple(
                            replace(e, supports_projection=True, projection_param="columns", params=e.params + ("columns",))
                            if (e.broker, e.origin, e.endpoint) == ("alerce", "ztf", "query_forced_photometry") else e
                            for e in graph.endpoint_capabilities))
    step = GetLightcurveStep(target=TargetSelector(ids=["A"], kind="object"),
                            sources=[Source(broker="alerce", origin="ztf")],
                            required_components=(SemanticReference(semantic_type="lightcurve",
                                field_path="forced_photometry_points.forced_photometry"),))
    assert validate_step_capabilities(step, graph).status == "supported"
    rejected = validate_step_capabilities(step, projected)
    assert rejected.status == "unsupported" and "alerce" in rejected.source_results[0].reason


def test_unknown_component_and_bare_component_noun_are_rejected(graph):
    executor = Executor()
    for tail in ("with lightcurve.no_such_component", "with forced_photometry"):
        result = validate_dsl(executor.lookup + tail, graph=graph, continue_from=None)
        assert not result.is_valid


def test_plain_plans_and_legacy_wire_format_remain_unchanged(graph):
    executor = Executor()
    plain = validate_dsl(executor.lookup + "with lightcurve", graph=graph, continue_from=None).compilation.workflow
    assert [p.endpoint for p in plan_workflow(plain, graph).steps[-1].endpoint_plans] == ["query_lightcurve"]
    assert not plain.steps[-1].required_components
    assert "required_components" not in plain.steps[-1].model_dump()
    legacy = WorkflowIR.model_validate({**plain.model_dump(), "dsl_version": 2})
    assert WorkflowIR.model_validate_json(legacy.model_dump_json()) == legacy
    target = TargetSelector(ids=[executor.object_id], kind="object")
    sources = [Source(broker="alerce", origin="ztf")]
    direct = WorkflowIR(steps=[GetLightcurveStep(target=target, sources=sources)])
    assert [(p.endpoint, p.required) for p in plan_workflow(direct, graph).steps[0].endpoint_plans] == [
        ("query_lightcurve", True), ("query_forced_photometry", False),
    ]


def test_general_component_rule_keeps_other_product_calls_optional(graph):
    step = GetLightcurveStep(target=TargetSelector(ids=["A"], kind="object"), sources=[Source(broker="alerce", origin="ztf")],
                            required_components=(SemanticReference(semantic_type="lightcurve", field_path="points"),))
    plans = plan_workflow(WorkflowIR(steps=[step]), graph).steps[0].endpoint_plans
    assert [(p.endpoint, p.required) for p in plans] == [("query_lightcurve", True), ("query_forced_photometry", False)]


def test_qualified_reference_does_not_promote_another_origin(graph):
    sources = [Source(broker="alerce", origin=origin) for origin in ("ztf", "lsst")]
    predicate = lower_expression_predicate("count(lightcurve@ztf:alerce.forced_photometry_points) >= 1",
                                          SemanticPathModel.from_ontology().record_types)
    workflow = WorkflowIR(steps=[LookupStep(target=TargetSelector(ids=["A"], kind="object"), sources=sources),
                                 GetLightcurveStep(sources=sources), FilterStep(predicate=predicate)])
    strengthened = require_referenced_components(workflow, graph)
    validation = validate_step_capabilities(strengthened.steps[1], graph)
    for source in validation.source_results:
        assert source.status == "supported"
        calls = source.recipes[0].calls
        assert len(calls) == (2 if source.source.origin == "ztf" else 1)


def test_sealed_prefix_is_immutable_and_explicit_new_request_reuses_only_required_calls(graph):
    executor = Executor()
    first = execute_dsl(executor.lookup + "with lightcurve", graph=graph, executor=executor, continue_from=None)
    calls, before = len(executor.calls), first.to_dict()
    unavailable = validate_dsl("filter " + count_for(executor), graph=graph, continue_from=first)
    assert not unavailable.is_runnable and "item 4a" in str(unavailable.lowering_error)
    second = execute_dsl("with lightcurve.forced_photometry_points\nfilter " + count_for(executor), graph=graph,
                         executor=executor, continue_from=first)
    assert len(second.portfolios) == 1
    assert [endpoint for endpoint, _ in executor.calls[calls:]] == ["query_forced_photometry"]
    assert second.workflow.steps[:len(first.workflow.steps)] == first.workflow.steps
    assert first.to_dict() == before


def test_empty_component_after_a_later_filter_does_not_pool_sibling_histories(graph):
    executor = Executor(empty=True)
    first = execute_dsl(executor.lookup + "with lightcurve", graph=graph, executor=executor, continue_from=None)
    result = execute_dsl("filter summary.identity.object_id exists\n"
                         "with lightcurve.forced_photometry_points\nfilter " + count_for(executor, "= 0"),
                         graph=graph, executor=executor, continue_from=first)
    assert len(result.portfolios) == 1
    assert result.workflow.steps[:len(first.workflow.steps)] == first.workflow.steps


@pytest.mark.parametrize("payload", [None, [{}]])
def test_empty_and_normalization_loss_are_not_confused(graph, payload):
    executor = Executor(malformed=True)
    executor.payloads[executor.forced_endpoint] = payload
    source = executor.lookup + "with lightcurve.forced_photometry_points\nfilter " + count_for(executor, "= 0")
    result = execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    assert result.portfolios == ()


def test_nested_component_does_not_become_a_second_record_noun(graph):
    result = validate_dsl("object ZTF18abbuksn from ztf via alerce\n"
                          "with crossmatch.classification from gaia via antares", graph=graph, continue_from=None)
    assert result.is_valid and result.is_runnable, result.lowering_error
    assert result.compilation.workflow.steps[-1].op == "get_crossmatch"


def test_sibling_arrays_are_distinct_but_two_actual_forced_products_stay_ambiguous(graph):
    executor = Executor("fink", "lsst")
    result = execute_dsl(executor.lookup + "with lightcurve\nfilter " + count_for(executor), graph=graph,
                         executor=executor, continue_from=None)
    assert len(result.portfolios) == 1
    portfolio = result.portfolios[0]
    forced = next(r for r in portfolio.records if r.fields.get("forced_photometry_points"))
    competing = replace(forced, internal_record_id=InternalRecordId("component:another-product"))
    candidate = replace(portfolio, records=portfolio.records + (competing,))
    predicate = lower_expression_predicate(count_for(executor), SemanticPathModel.from_ontology().record_types)
    diagnostics = []
    assert evaluate_portfolio_predicate_truth(candidate, predicate, diagnostics=diagnostics) is None
    assert any("ambiguous_product" in message for message in diagnostics)


def test_component_ir_reuses_frozen_references_and_requires_version_three():
    component = SemanticReference(semantic_type="lightcurve", field_path="forced_photometry_points")
    step = GetLightcurveStep(required_components=(component,))
    assert WorkflowIR.model_validate_json(WorkflowIR(steps=[step]).model_dump_json()).steps[0] == step
    for version in (1, 2):
        with pytest.raises(ValidationError, match="required components require dsl_version 3"):
            WorkflowIR(steps=[step], dsl_version=version)
    with pytest.raises(ValidationError):
        component.field_path = "points"
    with pytest.raises(ValidationError, match="duplicate-free"):
        GetLightcurveStep(required_components=(component, component))
    with pytest.raises(ValidationError, match="unknown component"):
        GetMeasurementStep(required_components=(component,))
