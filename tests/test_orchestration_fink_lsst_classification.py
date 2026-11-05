"""Composed Fink/Rubin classification retrieval, using unchanged frozen captures."""

from copy import deepcopy
from dataclasses import replace
from itertools import count
import json
from pathlib import Path
import shutil

import pytest
import yaml

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import EndpointRegistry, ExecutionResult
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import SurfaceLoweringError
from alertissimo.orchestration.binding import bind_endpoint_calls
from alertissimo.orchestration.ir import GetClassificationStep, Source, TargetSelector
from alertissimo.orchestration.planner import PlanningAmbiguityError, PlanningDeferredError, plan_step
from alertissimo.orchestration.runtime import EndpointPlan, EndpointPlanRef, WorkflowExecutionError
from alertissimo.orchestration.normalization import summary_object_identity
from alertissimo.orchestration.validation import validate_step_capabilities


FIXTURES = Path(__file__).parent / "fixtures/fink/lsst"
OID = "170587117485817955"
LOOKUP = f"object {OID} from lsst via fink\n"


def payload(endpoint):
    return json.loads((FIXTURES / f"{endpoint}.json").read_text())


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def get(classifier=None, ids=(OID,)):
    return GetClassificationStep(
        sources=[Source(broker="fink", origin="lsst")], classifier=classifier,
        target=TargetSelector(ids=list(ids), kind="object") if ids is not None else None,
    )


@pytest.mark.parametrize("classifier", [None, "fink", "FINK"])
@pytest.mark.parametrize("ids", [(OID,), (OID, "170587117485817956")])
def test_one_recipe_requires_object_labels_and_source_assessments(graph, classifier, ids):
    step = get(classifier, ids)
    result = validate_step_capabilities(step, graph)
    assert result.status == "supported"
    recipe, = result.source_results[0].recipes
    assert [call.endpoint for call in recipe.calls] == ["objects", "sources"]
    plans = plan_step(step, graph)
    assert [plan.endpoint for plan in plans] == ["objects", "sources"]
    for plan in plans:
        assert plan.required and plan.execution_reuse_from is None
        assert plan.parameter_sources == {"diaObjectId": ("target", "ids")}
        assert EndpointPlan.model_validate_json(plan.model_dump_json()) == plan
        call, = bind_endpoint_calls(step, plan, EndpointRegistry())
        assert call.params == {"diaObjectId": ",".join(ids)}


class Executor:
    def __init__(self, *, fail_sources=False, empty_sources=False):
        self.calls, self.ids = [], count()
        self.fail_sources, self.empty_sources = fail_sources, empty_sources

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        params = dict(params or {})
        assert (broker, origin) == ("fink", "lsst")
        assert params == {"diaObjectId": OID}
        assert endpoint in {"objects", "sources"}
        self.calls.append(endpoint)
        if endpoint == "sources" and self.fail_sources:
            raise RuntimeError("source evidence request failed")
        rows = [] if endpoint == "sources" and self.empty_sources else payload(endpoint)
        return ExecutionResult(payload=deepcopy(rows), execution_provenance=InternalExecutionProvenance(
            internal_execution_id=InternalExecutionId(f"classification:{next(self.ids)}"),
            broker=broker, origin=origin, endpoint=endpoint, params=params,
        ))


def endpoint(portfolio, record):
    return portfolio.execution(record.internal_source.internal_execution_id).endpoint


@pytest.mark.parametrize("classifier", [None, "fink"])
def test_public_retrieval_preserves_both_evidence_levels_and_source_rows(graph, classifier):
    suffix = "" if classifier is None else f" from {classifier}"
    source = LOOKUP + f"with classification{suffix} via fink\n"
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    check, = (check for check in validation.capabilities.checks if check.subject == "requirement")
    assert {name for item in check.evidence for name in item.endpoints} == {"objects", "sources"}
    executor = Executor()
    result = execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    assert executor.calls == ["objects", "sources"]
    object_plan, source_plan = result.run.steps[1].endpoint_plans
    assert object_plan.execution_reuse_from == EndpointPlanRef(step_index=0, plan_index=0)
    assert source_plan.execution_reuse_from is None
    portfolio, = result.portfolios
    assert summary_object_identity(portfolio) == ("lsst", OID)
    classes = [record for record in portfolio.records if record.semantic_type == "classification@fink"]
    labels = [record for record in classes if record.get("best.class") is not None]
    assert len(labels) == 1 and endpoint(portfolio, labels[0]) == "objects"
    assessments = [record for record in classes if record.get("assessment.cats.score") is not None]
    assert len(assessments) == len(payload("sources")) == 16
    for record in assessments:
        assert endpoint(portfolio, record) == "sources"
        row = payload("sources")[record.internal_source.payload_index]
        assert record.get("assessment.cats.score") == row["f:clf_cats_score"]
    assert sum(record.semantic_type == "measurement@lsst:fink" for record in portfolio.records) == 16
    physical = [execution for step in result.staged.execution.steps for execution in step.executions
                if execution.execution_provenance.endpoint == "sources"]
    assert len(physical) == 1 and physical[0].payload == payload("sources")


def test_continuation_preserves_prefix_and_does_not_repeat_object_or_source_requests(graph):
    executor = Executor()
    first = execute_dsl(LOOKUP, graph=graph, executor=executor, continue_from=None)
    snapshot = first.to_dict()
    second = execute_dsl("with classification via fink\n", graph=graph, executor=executor, continue_from=first)
    third = execute_dsl("filter exists classification@fink:fink.assessment.cats.score\n",
                        graph=graph, executor=executor, continue_from=second)
    assert executor.calls == ["objects", "sources"]
    assert first.to_dict() == snapshot
    assert second.workflow.steps[:len(first.workflow.steps)] == first.workflow.steps
    assert third.workflow.steps[:len(second.workflow.steps)] == second.workflow.steps
    assert {summary_object_identity(p) for p in third.portfolios} == {("lsst", OID)}
    assert sum(r.semantic_type == "measurement@lsst:fink" for p in third.portfolios for r in p.records) == 16


def test_required_source_call_failure_is_not_silently_partial_success(graph):
    executor = Executor(fail_sources=True)
    with pytest.raises(WorkflowExecutionError, match="source evidence request failed"):
        execute_dsl(LOOKUP + "with classification via fink\n", graph=graph, executor=executor, continue_from=None)
    assert executor.calls == ["objects", "sources"]


def test_empty_source_response_is_not_an_invented_assessment(graph):
    executor = Executor(empty_sources=True)
    result = execute_dsl(LOOKUP + "with classification via fink\n",
                         graph=graph, executor=executor, continue_from=None)
    portfolio, = result.portfolios
    assert any(r.get("best.class") is not None for r in portfolio.records if r.semantic_type == "classification@fink")
    assert not any(r.get("assessment.cats.score") is not None for r in portfolio.records)
    assert executor.calls == ["objects", "sources"]


@pytest.mark.parametrize("classifier", ["cats", "unknown_model"])
def test_assessment_names_are_not_invented_producers(graph, classifier):
    executor = Executor()
    with pytest.raises(SurfaceLoweringError):
        execute_dsl(LOOKUP + f"with classification from {classifier} via fink\n",
                    graph=graph, executor=executor, continue_from=None)
    assert executor.calls == []


@pytest.mark.parametrize("change", ["constant_target", "dependency", "optional", "unmapped"])
def test_every_composite_call_needs_its_own_classification_and_target_evidence(tmp_path, change):
    root = tmp_path / "providers"
    destination = root / "fink/lsst"
    shutil.copytree(PROVIDERS_ROOT / "fink/lsst", destination)
    path = destination / "capabilities.yaml"
    doc = yaml.safe_load(path.read_text())
    call = doc["recipes"]["get_classification"][0]["calls"][1]
    if change == "constant_target":
        call["params"]["diaObjectId"] = {"value": OID}
    elif change == "dependency":
        call["params"]["diaObjectId"] = {"from": {"call": 0, "path": "summary.identity.object_id"}}
    elif change == "optional":
        call["required"] = False
    else:
        call["endpoint"] = "fp"
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    with pytest.raises(PlanningDeferredError, match="classification"):
        plan_step(get(), build_capability_graph(root))


def test_requested_producer_must_be_supplied_by_each_composite_call(graph):
    recipe, = graph.query_recipes(broker="fink", origin="lsst", op="get_classification")
    first, second = recipe.calls
    other = replace(second, outputs=tuple(
        replace(field, semantic_record_type="classification@other")
        if field.semantic_record_type.startswith("classification@") else field
        for field in second.outputs
    ))
    changed = replace(graph, recipe_capabilities=tuple(
        replace(item, calls=(first, other)) if item is recipe else item
        for item in graph.recipe_capabilities
    ))
    assert validate_step_capabilities(get(), changed).status == "supported"
    assert validate_step_capabilities(get("fink"), changed).status == "unsupported"


def test_duplicate_composite_recipes_remain_ambiguous(graph):
    recipe, = graph.query_recipes(broker="fink", origin="lsst", op="get_classification")
    changed = replace(graph, recipe_capabilities=(*graph.recipe_capabilities, replace(recipe, alternative_index=1)))
    with pytest.raises(PlanningAmbiguityError):
        plan_step(get(), changed)
