"""Verified Fink JSON product mode with synthetic image stamps; no network."""

from copy import deepcopy

import pytest

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import (
    EndpointRegistry, EndpointSpec, ExecutionResult, RegistryEndpointExecutor, TransportResult,
)
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.data_layer.runtime.record_builder import build_portfolios_from_execution
from alertissimo.orchestration.binding import bind_endpoint_calls
from alertissimo.orchestration.ir import GetCutoutStep, GetDataProductStep, Source, TargetSelector
from alertissimo.orchestration.normalization import normalize_workflow_execution, summary_object_identity
from alertissimo.orchestration.planner import PlanningDeferredError, plan_step
from alertissimo.orchestration.runtime import WorkflowExecutionError


IDS = ("ZTF21abfmbix", "ZTF20acpwljl")
STAMPS = {
    "b:cutoutScience_stampData": [[1.0, None], [-5.0, 4.0]],
    "b:cutoutTemplate_stampData": [[11.0, 12.0], [13.0, 14.0]],
    "b:cutoutDifference_stampData": [[-10.0, -12.0], [-18.0, -10.0]],
}
ROLES = {"science": "b:cutoutScience_stampData", "template": "b:cutoutTemplate_stampData",
         "difference": "b:cutoutDifference_stampData"}
SOURCE = f"objects {IDS[0]}, {IDS[1]} from ztf via fink\n"


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


class ReplayTransport:
    def __init__(self, payload=STAMPS):
        self.payload = deepcopy(payload)
        self.calls = []

    def execute(self, spec, params, headers=None):
        assert (spec.broker, spec.origin) == ("fink", "ztf")
        self.calls.append((spec.endpoint, deepcopy(dict(params))))
        if spec.endpoint == "objects":
            return TransportResult([
                {"i:objectId": oid, "i:candid": IDS.index(oid) + 1,
                 "i:fid": 1, "i:jd": 2459000.5, "i:magpsf": 20.0,
                 "i:drb": 0.95 if oid == IDS[0] else 0.2}
                for oid in params["objectId"].split(",")
            ], content_type="application/json", status_code=200)
        assert spec.endpoint == "cutouts_array"
        assert params["kind"] == "All" and params["output-format"] == "array"
        assert params["objectId"] in IDS and "," not in params["objectId"]
        return TransportResult(deepcopy(self.payload), content_type="application/json", status_code=200)


def executor(transport):
    return RegistryEndpointExecutor(transports={"rest": transport})


@pytest.mark.parametrize("step_type", [GetCutoutStep, GetDataProductStep])
def test_json_mode_preserves_object_fanout_and_has_no_dynamic_format_selection(graph, step_type):
    step = step_type(target=TargetSelector(ids=list(IDS), kind="object"),
                     sources=[Source(broker="fink", origin="ztf")])
    plan, = plan_step(step, graph)
    assert plan.endpoint == "cutouts_array" and plan.execution_reuse_from is None
    calls = bind_endpoint_calls(step, plan, EndpointRegistry())
    assert [call.params["objectId"] for call in calls] == list(IDS)
    spec = EndpointRegistry().resolve("fink", "ztf", plan.endpoint)
    assert spec.fixed_params == {"kind": "All", "output-format": "array"}
    assert set(spec.required_matrices) == set(STAMPS)


def test_public_data_product_retains_all_stamps_under_the_correct_candidate(graph):
    transport = ReplayTransport()
    source = SOURCE + "with data_product via fink\n"
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    result = execute_dsl(source, graph=graph, executor=executor(transport), continue_from=None)
    assert {summary_object_identity(p)[1] for p in result.portfolios} == set(IDS)
    requests = [params for endpoint, params in transport.calls if endpoint == "cutouts_array"]
    assert [params["objectId"] for params in requests] == list(IDS)
    expected = {role: STAMPS[field] for role, field in ROLES.items()}
    for portfolio in result.portfolios:
        product, = [r for r in portfolio.records if r.semantic_type == "data_product@ztf:fink"]
        assert product.get("payload") == expected
        provenance, = [e for e in portfolio.executions if e.endpoint == "cutouts_array"]
        assert provenance.params["objectId"] == summary_object_identity(portfolio)[1]
        assert product.internal_source.internal_execution_id == provenance.internal_execution_id
    serialized = result.to_dict()
    for portfolio in serialized["portfolios"]:
        product, = [r for r in portfolio["records"] if r["semantic_type"] == "data_product@ztf:fink"]
        assert product["fields"]["payload"] == expected
    replay = normalize_workflow_execution(result.staged.execution)
    assert {summary_object_identity(p)[1] for p in replay.steps[-1].portfolios} == set(IDS)
    assert transport.payload == STAMPS  # No stretching, clipping or null replacement.


def test_enrichment_family_executes_concrete_steps_and_replays_without_new_calls(graph):
    transport = ReplayTransport()
    endpoint_executor = executor(transport)
    first = execute_dsl(SOURCE + "with enrichment\n", graph=graph,
                        executor=endpoint_executor, continue_from=None)
    assert {step.op for step in first.workflow.steps} == {
        "lookup", "get_classification", "get_crossmatch", "get_data_product", "get_lightcurve",
    }
    assert {summary_object_identity(p)[1] for p in first.portfolios} == set(IDS)
    for portfolio in first.portfolios:
        families = {record.semantic_type.split("@", 1)[0] for record in portfolio.records}
        assert {"measurement", "lightcurve", "data_product"} <= families
        assert not {"detection", "enrichment"} & families
    calls = deepcopy(transport.calls)
    second = execute_dsl("with enrichment via fink\n", graph=graph,
                         executor=endpoint_executor, continue_from=first)
    assert second.workflow.steps == first.workflow.steps
    assert transport.calls == calls
    replay = normalize_workflow_execution(second.staged.execution)
    assert {summary_object_identity(p)[1] for p in replay.steps[-1].portfolios} == set(IDS)


def test_admitted_family_member_failure_is_not_silently_ignored(graph):
    with pytest.raises(WorkflowExecutionError, match="required matri"):
        execute_dsl(SOURCE + "with enrichment\n", graph=graph,
                    executor=executor(ReplayTransport({})), continue_from=None)


def test_continuation_fetches_images_only_for_filter_survivors(graph):
    transport = ReplayTransport()
    endpoint_executor = executor(transport)
    first = execute_dsl(SOURCE, graph=graph, executor=endpoint_executor, continue_from=None)
    before = deepcopy(transport.calls)
    second = execute_dsl("filter measurement@ztf:fink.quality.real_bogus >= 0.9\nwith data_product via fink\n",
                         graph=graph, executor=endpoint_executor, continue_from=first)
    assert transport.calls[:len(before)] == before
    assert [(endpoint, params["objectId"]) for endpoint, params in transport.calls[len(before):]] == [
        ("cutouts_array", IDS[0]),
    ]
    assert {summary_object_identity(p)[1] for p in second.portfolios} == {IDS[0]}
    assert {summary_object_identity(p)[1] for p in first.portfolios} == set(IDS)
    assert {summary_object_identity(p)[1] for p in normalize_workflow_execution(second.staged.execution).steps[-1].portfolios} == {IDS[0]}


@pytest.mark.parametrize("payload", [b"", b"PNG bytes", [], {}, {"error": "no archive"},
    {key: value for key, value in STAMPS.items() if "Template" not in key},
    *[{**STAMPS, "b:cutoutScience_stampData": matrix} for matrix in (
        None, [], [[]], [1, 2], [[1], [2, 3]], [["bad"]], [[True]],
    )],
])
def test_missing_archive_binary_or_malformed_stamps_fail_the_required_call(graph, payload):
    transport = ReplayTransport(payload)
    with pytest.raises(WorkflowExecutionError, match="required matri"):
        execute_dsl(SOURCE + "with data_product via fink\n", graph=graph,
                    executor=executor(transport), continue_from=None)


@pytest.mark.parametrize("step", [
    GetCutoutStep(format="FITS"), GetCutoutStep(format="PNG"), GetCutoutStep(size=5),
    GetDataProductStep(product_type="spectrum"),
])
def test_array_activation_does_not_ignore_unsupported_product_selectors(graph, step):
    step = step.model_copy(update={"sources": [Source(broker="fink", origin="ztf")],
                                  "target": TargetSelector(ids=[IDS[0]], kind="object")})
    with pytest.raises(PlanningDeferredError, match="product inputs lack verified"):
        plan_step(step, graph)


def test_legacy_raw_array_mapping_also_retains_every_named_stamp():
    execution = ExecutionResult(payload=deepcopy(STAMPS), execution_provenance=InternalExecutionProvenance(
        InternalExecutionId("cutout:legacy"), "fink", "ztf", "cutouts",
        params={"objectId": IDS[0], "kind": "All", "output-format": "array"},
    ))
    portfolio, = build_portfolios_from_execution(execution, validate_semantic_model=True)
    product, = [r for r in portfolio.records if r.semantic_type == "data_product@ztf:fink"]
    assert product.get("payload") == {role: STAMPS[field] for role, field in ROLES.items()}


@pytest.mark.parametrize("fields", ["image", [None], ["image", "image"]])
def test_required_matrix_declarations_reject_ambiguous_field_lists(fields):
    with pytest.raises(ValueError, match="required_matrices"):
        EndpointSpec("test", "ztf", "images", "rest", required_matrices=fields)
