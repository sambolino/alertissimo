"""Product calls require explicit identity and compatible normalization evidence."""

import shutil

import pytest
import yaml

from alertissimo.data_layer.execution import EndpointRegistry, ExecutionResult
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance
from alertissimo.data_layer.runtime.capability_graph import CapabilityGraphError, build_capability_graph
from alertissimo.data_layer.runtime.record_builder import build_portfolios_from_execution
from alertissimo.orchestration.binding import bind_endpoint_calls
from alertissimo.orchestration.ir import (
    FilterStep, GetCutoutStep, GetDataProductStep, LookupStep, Source, TargetSelector, WorkflowIR,
)
from alertissimo.orchestration.planner import PlanningDeferredError, UnsupportedStepError, plan_step, plan_workflow
from alertissimo.orchestration.runtime import CandidateInputRef, WorkflowRun
from alertissimo.orchestration.validation import validate_step_capabilities


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def product(step_type=GetCutoutStep, broker="fink", origin="ztf", kind="object", ids=("1", "2"), **inputs):
    return step_type(
        target=TargetSelector(ids=list(ids), kind=kind) if ids is not None else None,
        sources=[Source(broker=broker, origin=origin)], **inputs,
    )


def local_provider(tmp_path, broker="fink", origin="ztf"):
    root = tmp_path / "providers"
    destination = root / broker / origin
    shutil.copytree(PROVIDERS_ROOT / broker / origin, destination)
    return root, destination


def edit_yaml(path, update):
    doc = yaml.safe_load(path.read_text())
    update(doc)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


@pytest.mark.parametrize("step_type", [GetCutoutStep, GetDataProductStep])
@pytest.mark.parametrize("broker,origin,kind,reason", [
    ("alerce", "ztf", "object", "no mapped data_product material"),
    ("alerce", "lsst", "object", "no mapped data_product material"),
    ("fink", "ztf", "object", "response shape/mode"),
    ("fink", "lsst", "alert", "identity ownership lacks normalization evidence"),
])
def test_production_product_gaps_are_deferred_without_tag_fallback(graph, step_type, broker, origin, kind, reason):
    step = product(step_type, broker, origin, kind)
    result = validate_step_capabilities(step, graph)
    assert result.status == "deferred"
    assert result.candidates == ()
    with pytest.raises(PlanningDeferredError, match=reason):
        plan_step(step, graph)


@pytest.mark.parametrize("step_type", [GetCutoutStep, GetDataProductStep])
def test_lsst_alert_contract_never_accepts_object_or_implicit_candidate_ids(graph, step_type):
    for ids in (("1",), None):
        with pytest.raises(UnsupportedStepError, match="target kind 'object'"):
            plan_step(product(step_type, origin="lsst", ids=ids), graph)
    with pytest.raises(PlanningDeferredError, match="namespace is unspecified"):
        plan_step(product(step_type, origin="lsst", kind=None), graph)


@pytest.mark.parametrize("step_type", [GetCutoutStep, GetDataProductStep])
def test_object_product_recipes_do_not_accept_alert_ids(graph, step_type):
    with pytest.raises(UnsupportedStepError, match="target kind 'alert'"):
        plan_step(product(step_type, kind="alert"), graph)


def test_output_format_controls_are_compiled_from_existing_physical_roles(graph):
    for origin in ("ztf", "lsst"):
        recipe, = graph.query_recipes(broker="fink", origin=origin, op="get_cutout")
        call, = recipe.calls
        endpoint, = (item for item in graph.endpoints_for("fink", origin)
                     if item.endpoint == call.endpoint)
        assert endpoint.output_format_params == ("output-format",)
        assert endpoint.binding_roles == ("target_id",)
    assert all(
        call.endpoint != "get_avro"
        for recipe in graph.query_recipes(broker="alerce", origin="lsst", op="get_data_product")
        for call in recipe.calls
    )  # The physically disabled LSST AVRO path is not authored.


@pytest.mark.parametrize("op", ["get_cutout", "get_data_product"])
@pytest.mark.parametrize("kind", [None, "unknown", 1])
def test_product_recipe_namespaces_are_validated_against_the_ir(tmp_path, op, kind):
    root, destination = local_provider(tmp_path)
    def invalid(doc):
        doc["recipes"][op][0]["target_kind"] = kind
    edit_yaml(destination / "capabilities.yaml", invalid)
    with pytest.raises(CapabilityGraphError, match="target_kind must be"):
        build_capability_graph(root)


@pytest.mark.parametrize("op", ["get_cutout", "get_data_product"])
@pytest.mark.parametrize("kind", ["source", "detection"])
def test_product_recipe_namespaces_preserve_the_existing_ir_kinds(tmp_path, op, kind):
    root, destination = local_provider(tmp_path)
    def valid(doc):
        doc["recipes"][op][0]["target_kind"] = kind
    edit_yaml(destination / "capabilities.yaml", valid)
    recipe, = build_capability_graph(root).query_recipes(broker="fink", origin="ztf", op=op)
    assert recipe.target_kind == kind


def json_product_provider(tmp_path):
    """Synthetic JSON contract, without image response-mode controls."""
    root, destination = local_provider(tmp_path)
    def json_endpoint(doc):
        endpoint = doc["endpoints"]["cutouts"]
        endpoint["output"] = {"type": "object", "item": "product"}
        endpoint["params"].pop("kind")
        endpoint["params"].pop("output-format")
        endpoint["operation_types"] = []
    edit_yaml(destination / "endpoints.yaml", json_endpoint)
    def json_calls(doc):
        for op in ("get_cutout", "get_data_product"):
            params = doc["recipes"][op][0]["calls"][0]["params"]
            params.pop("kind")
            params.pop("output-format")
    edit_yaml(destination / "capabilities.yaml", json_calls)
    def json_fields(doc):
        doc["mappings"]["data_product@ztf:fink.payload"] = ["cutouts#content"]
        doc["mappings"]["data_product@ztf:fink.type"] = ["cutouts#type"]
    edit_yaml(destination / "mappings.yaml", json_fields)
    return root, destination


@pytest.mark.parametrize("step_type", [GetCutoutStep, GetDataProductStep])
def test_verified_json_product_uses_existing_fanout_and_normalization(tmp_path, step_type):
    root, _ = json_product_provider(tmp_path)
    step = product(step_type)
    plan, = plan_step(step, build_capability_graph(root))
    assert plan.parameter_sources == {"objectId": ("target", "ids")}
    calls = bind_endpoint_calls(step, plan, EndpointRegistry(root))
    assert [call.params for call in calls] == [{"objectId": "1"}, {"objectId": "2"}]
    for index, call in enumerate(calls):
        execution = ExecutionResult(
            payload={"content": f"content-{index}", "type": "cutout"},
            execution_provenance=InternalExecutionProvenance(
                InternalExecutionId(f"execution:product:{index}"), "fink", "ztf", "cutouts", params=call.params,
            ),
        )
        portfolio, = build_portfolios_from_execution(execution, providers_root=root, validate_semantic_model=True)
        record, = (record for record in portfolio.records if record.semantic_type.startswith("data_product@"))
        assert record.semantic_type == "data_product@ztf:fink"
        assert record.fields["payload"] == f"content-{index}"
        assert record.fields["type"] == "cutout"


def test_declared_json_type_does_not_override_unverified_response_modes(tmp_path):
    root, destination = local_provider(tmp_path)
    def json_type(doc):
        doc["endpoints"]["cutouts"]["output"]["type"] = "object"
    edit_yaml(destination / "endpoints.yaml", json_type)
    with pytest.raises(PlanningDeferredError, match="response shape/mode"):
        plan_step(product(), build_capability_graph(root))


@pytest.mark.parametrize("step_type,inputs", [
    (GetCutoutStep, {"format": "FITS"}), (GetCutoutStep, {"size": 3.0}),
    (GetDataProductStep, {"product_type": "cutout"}),
])
def test_unverified_product_selectors_are_not_silently_ignored(tmp_path, step_type, inputs):
    root, _ = json_product_provider(tmp_path)
    with pytest.raises(PlanningDeferredError, match="product inputs lack verified"):
        plan_step(product(step_type, **inputs), build_capability_graph(root))


def test_recipe_target_assignment_preserves_cutout_candidate_flow(tmp_path):
    root, _ = json_product_provider(tmp_path)
    get = product(ids=None)
    workflow = WorkflowIR(steps=[
        LookupStep(target=TargetSelector(ids=["1", "2"], kind="object"), sources=get.sources),
        FilterStep(criteria={}), get,
    ])
    run = plan_workflow(workflow, build_capability_graph(root))
    assert WorkflowRun.model_validate_json(run.model_dump_json()) == run
    plan, = run.steps[2].endpoint_plans
    assert plan.candidate_input_from == CandidateInputRef(step_index=1)
    assert plan.execution_reuse_from is None
    calls = bind_endpoint_calls(get, plan, EndpointRegistry(root), runtime_values={"target_id": ["2"]})
    assert calls[0].params == {"objectId": "2"}
