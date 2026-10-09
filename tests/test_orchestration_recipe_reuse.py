"""Recipe reuse must survive required/optional execution and call-local evidence."""

from dataclasses import replace
import json
from pathlib import Path
import shutil

import pytest
import yaml

from alertissimo.data_layer.execution import EndpointRegistry, ExecutionResult
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph, canonical_semantic_noun
from alertissimo.orchestration.ir import GetClassificationStep, SemanticSearchStep, Source, WorkflowIR
from alertissimo.orchestration.ir.predicates import ComparisonPredicate, PredicateLiteral, SemanticReference
from alertissimo.orchestration.pipeline import execute_staged_workflow_run
from alertissimo.orchestration.planner import PlanningDeferredError, plan_workflow
from alertissimo.orchestration.runtime import CandidateInputRef, EndpointPlanRef, StepRunState, WorkflowRun


def discovery_workflow(tmp_path, *, required, preceding_source=False):
    root = tmp_path / "providers"
    destination = root / "alerce" / "lsst"
    shutil.copytree(PROVIDERS_ROOT / "alerce" / "lsst", destination)
    path = destination / "capabilities.yaml"
    doc = yaml.safe_load(path.read_text())
    doc["recipes"]["semantic_search"][0]["calls"].append({
        "endpoint": "query_probabilities", "required": required,
        "params": {"oid": {"from": {"call": 0, "path": "summary.identity.object_id"}}},
    })
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    sources = [Source(broker="alerce", origin="lsst")]
    if preceding_source:
        shutil.copytree(PROVIDERS_ROOT / "alerce" / "ztf", root / "alerce" / "ztf")
        sources.insert(0, Source(broker="alerce", origin="ztf"))
    workflow = WorkflowIR(steps=[
        SemanticSearchStep(semantic_type="summary", sources=sources),
        GetClassificationStep(sources=[Source(broker="alerce", origin="lsst")]),
    ])
    return workflow, build_capability_graph(root)


@pytest.mark.parametrize("required", [False, True])
@pytest.mark.parametrize("preceding_source", [False, True])
def test_only_required_discovery_material_is_reused(tmp_path, required, preceding_source):
    workflow, graph = discovery_workflow(tmp_path, required=required, preceding_source=preceding_source)
    run = plan_workflow(workflow, graph)
    consumer, = run.steps[1].endpoint_plans
    owner_index = 2 if preceding_source else 1
    assert run.steps[0].endpoint_plans[owner_index].required is required
    if required:
        assert consumer.execution_reuse_from == EndpointPlanRef(step_index=0, plan_index=owner_index)
        assert consumer.candidate_input_from is None
    else:
        assert consumer.execution_reuse_from is None
        assert consumer.candidate_input_from == CandidateInputRef(step_index=0)
    assert WorkflowRun.model_validate_json(run.model_dump_json()) == run


class OptionalFailureExecutor:
    """Fail the optional attempt, then serve the later mandatory retrieval."""

    def __init__(self):
        self.calls = []
        self.probability_attempts = 0

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        supplied = dict(params or {})
        self.calls.append((endpoint, supplied))
        fixture_root = Path(__file__).parents[1]
        if endpoint == "query_objects":
            fixture = fixture_root / "scripts/smoke/fixtures/alerce_lsst_query_objects_filtered.json"
        elif endpoint == "query_probabilities":
            self.probability_attempts += 1
            if self.probability_attempts == 1:
                raise RuntimeError("controlled optional classification outage")
            fixture = fixture_root / "tests/fixtures/alerce/lsst/query_probabilities.json"
        else:
            raise AssertionError(f"unexpected endpoint {endpoint}")
        return ExecutionResult(
            payload=json.loads(fixture.read_text(encoding="utf-8")),
            execution_provenance=InternalExecutionProvenance(
                internal_execution_id=InternalExecutionId(f"execution:recipe-reuse:{len(self.calls)}"),
                broker=broker, origin=origin, endpoint=endpoint, params=supplied,
                status="success", transport="fixture",
            ),
        )


def test_failed_optional_material_does_not_prevent_required_retrieval(tmp_path):
    workflow, graph = discovery_workflow(tmp_path, required=False)
    executor = OptionalFailureExecutor()
    staged = execute_staged_workflow_run(plan_workflow(workflow, graph), EndpointRegistry(), executor)
    owner, consumer = staged.run.steps
    assert owner.state is StepRunState.SUCCEEDED
    assert owner.execution_plan_indexes == (0,)
    assert len(owner.warnings) == 1
    assert "controlled optional classification outage" in owner.warnings[0]
    assert consumer.state is StepRunState.SUCCEEDED
    assert consumer.execution_plan_indexes == (0,)
    assert consumer.execution_ids == ("execution:recipe-reuse:3",)
    assert [endpoint for endpoint, _ in executor.calls] == [
        "query_objects", "query_probabilities", "query_probabilities",
    ]
    assert executor.calls[1][1] == executor.calls[2][1] == {"oid": 170587117485817955}


@pytest.mark.parametrize("classification_output", [False, True])
def test_owned_reuse_uses_compiled_call_outputs_instead_of_legacy_families(classification_output):
    graph = build_capability_graph()
    # Keep the endpoint-family index intact while constraining the compiled call.
    graph = replace(graph, recipe_capabilities=tuple(
        replace(recipe, calls=tuple(
            replace(call, outputs=tuple(
                output for output in call.outputs
                if classification_output or canonical_semantic_noun(output.semantic_record_type) != "classification"
            )) for call in recipe.calls
        )) if (recipe.op, recipe.broker, recipe.origin) == ("semantic_search", "alerce", "lsst") else recipe
        for recipe in graph.recipe_capabilities
    ))
    sources = [Source(broker="alerce", origin="lsst")]
    workflow = WorkflowIR(steps=[
        SemanticSearchStep(
            semantic_type="summary", sources=sources,
            predicate=ComparisonPredicate(
                left=SemanticReference(semantic_type="classification", producer="lc_classifier", field_path="best.class"),
                operator="=", right=PredicateLiteral(value="SN"),
            ),
        ),
        GetClassificationStep(classifier="lc_classifier", sources=sources),
    ])
    if classification_output:
        run = plan_workflow(workflow, graph)
        assert run.steps[1].endpoint_plans[0].execution_reuse_from == EndpointPlanRef(step_index=0, plan_index=0)
    else:
        with pytest.raises(PlanningDeferredError, match="dynamic producer mapping"):
            plan_workflow(workflow, graph)
