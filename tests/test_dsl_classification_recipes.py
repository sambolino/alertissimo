"""Classification requirements use fresh recipes or actual discovery ownership."""

import shutil

import pytest
import yaml

from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import (
    SurfaceCapabilityStatus, SurfaceLoweringError, compile_surface_fragment,
    compile_surface_to_ir, lower_surface, parse_surface_fragment, parse_surface_script,
    validate_surface_capabilities, validate_surface_fragment_capabilities,
)
from alertissimo.orchestration.ir import FilterStep, LookupStep, SearchSelection, TargetSelector, WorkflowIR
from alertissimo.orchestration.planner import PlanningDeferredError, plan_workflow
from alertissimo.orchestration.runtime import EndpointPlanRef
from alertissimo.orchestration.validation import classification_material_capabilities, validate_step_capabilities


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def classification_check(report):
    check, = (check for check in report.checks if check.subject == "requirement" and check.semantic_noun == "classification")
    return check


@pytest.mark.parametrize("source, status", [
    ("objects 1 from lsst via alerce\nwith classification\n", "supported"),
    ("objects 1 from lsst via alerce\nwith classification from lc_classifier\n", "deferred"),
    ("objects ZTF1 from ztf via fink\nwith classification from fink\n", "supported"),
    ("objects ZTF1 from ztf via fink\nwith classification from unknown\n", "unsupported"),
])
def test_fresh_classification_matches_lowered_get(graph, source, status):
    surface = parse_surface_script(source)
    step = lower_surface(surface).workflow.steps[1]
    result = validate_step_capabilities(step, graph)
    report = validate_surface_capabilities(surface, graph=graph)
    check = classification_check(report)
    assert check.status.value == result.status == status
    assert check.reason == result.source_results[0].reason
    assert {name for item in check.evidence for name in item.endpoints} == {
        endpoint.endpoint for endpoint in result.candidates
    }
    if status == "supported":
        assert compile_surface_to_ir(surface, graph=graph).steps[1] == step
    else:
        assert check.evidence == ()
        with pytest.raises(SurfaceLoweringError) as caught:
            compile_surface_to_ir(surface, graph=graph)
        assert caught.value.code == f"{status}_capability"


@pytest.mark.parametrize("clauses", [
    'with classification from lc_classifier where best.class = "SN"\n',
    'where classification@lc_classifier.best.class = "SN"\n',
    'where classification@lc_classifier.best.class = "SN"\nwith classification from lc_classifier\n',
])
def test_qualified_discovery_material_preserves_emitted_retrieval(graph, clauses):
    surface = parse_surface_script("objects from lsst via alerce\n" + clauses)
    workflow = lower_surface(surface).workflow
    owner, consumer = workflow.steps
    assert validate_step_capabilities(consumer, graph).status == "deferred"
    material, = classification_material_capabilities(consumer, (owner,), graph)
    report = validate_surface_capabilities(surface, graph=graph)
    check = classification_check(report)
    assert report.status is SurfaceCapabilityStatus.SUPPORTED
    assert "required discovery material" in check.reason
    assert check.producer == "lc_classifier"
    assert check.evidence[0].semantic_record_type == material.record_types[0]
    assert check.evidence[0].endpoints == (material.endpoint.endpoint,)
    assert compile_surface_to_ir(surface, graph=graph) == workflow
    run = plan_workflow(workflow, graph)
    assert run.steps[1].endpoint_plans[0].execution_reuse_from == EndpointPlanRef(step_index=0, plan_index=0)


def test_later_explicit_requirement_keeps_the_intervening_filter(graph):
    surface = parse_surface_script(
        "objects from lsst via alerce\n"
        'where classification@lc_classifier.best.class = "SN"\n'
        "filter exists summary.identity.object_id\n"
        "with classification from lc_classifier\n"
    )
    workflow = lower_surface(surface).workflow
    assert [step.op for step in workflow.steps] == ["semantic_search", "filter", "get_classification"]
    check = classification_check(validate_surface_capabilities(surface, graph=graph))
    assert check.status is SurfaceCapabilityStatus.DEFERRED
    assert check.evidence == ()
    with pytest.raises(PlanningDeferredError):
        plan_workflow(workflow, graph)
    with pytest.raises(SurfaceLoweringError) as caught:
        compile_surface_to_ir(surface, graph=graph)
    assert caught.value.code == "deferred_capability"


def test_a_later_lowering_failure_does_not_erase_earlier_discovery_proof(graph):
    surface = parse_surface_script(
        "objects from lsst via alerce\n"
        'with classification from lc_classifier where best.class = "SN"\n'
        "with data_product science\n"
    )
    check = classification_check(validate_surface_capabilities(surface, graph=graph))
    assert check.status is SurfaceCapabilityStatus.SUPPORTED
    assert "required discovery material" in check.reason


def local_provider(tmp_path):
    root = tmp_path / "providers"
    destination = root / "alerce" / "lsst"
    shutil.copytree(PROVIDERS_ROOT / "alerce" / "lsst", destination)
    return root, destination


def edit_yaml(path, update):
    doc = yaml.safe_load(path.read_text())
    update(doc)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def test_valid_classification_routes_do_not_need_operation_tags(tmp_path):
    root, destination = local_provider(tmp_path)
    def remove_tags(doc):
        for endpoint in doc["endpoints"].values():
            endpoint["operation_types"] = []
    edit_yaml(destination / "endpoints.yaml", remove_tags)
    graph = build_capability_graph(root)
    for source in (
        "objects 1 from lsst via alerce\nwith classification\n",
        'objects from lsst via alerce\nwith classification from lc_classifier where best.class = "SN"\n',
    ):
        surface = parse_surface_script(source)
        assert validate_surface_capabilities(surface, graph=graph).status is SurfaceCapabilityStatus.SUPPORTED
        assert plan_workflow(compile_surface_to_ir(surface, graph=graph), graph)


def test_unbindable_owned_classification_does_not_borrow_family_or_selector_evidence(tmp_path):
    root, destination = local_provider(tmp_path)
    def invalid(doc):
        call = doc["recipes"]["get_classification"][0]["calls"][0]
        call["params"]["oid"] = {"value": 123}
    edit_yaml(destination / "capabilities.yaml", invalid)
    graph = build_capability_graph(root)
    surface = parse_surface_script(
        'objects from lsst via alerce\nwith classification from lc_classifier where best.class = "SN"\n'
    )
    check = classification_check(validate_surface_capabilities(surface, graph=graph))
    assert check.status is SurfaceCapabilityStatus.DEFERRED
    assert "does not bind the target identities" in check.reason
    assert check.evidence == ()


def discovery_base():
    surface = parse_surface_script(
        'objects from lsst via alerce\nwhere classification@lc_classifier.best.class = "SN"\n'
    )
    owner = lower_surface(surface).workflow.steps[0]
    return WorkflowIR(steps=[owner])


@pytest.mark.parametrize("barrier", [None, "filter", "selection", "lookup"])
def test_continuation_uses_actual_base_workflow(graph, barrier):
    base = discovery_base()
    owner = base.steps[0]
    if barrier == "filter":
        base = WorkflowIR(steps=[owner, FilterStep(predicate=owner.predicate)])
    elif barrier == "selection":
        base = WorkflowIR(steps=[owner.model_copy(update={"selection": SearchSelection(latest=1)})])
    elif barrier == "lookup":
        base = WorkflowIR(steps=[LookupStep(target=TargetSelector(ids=["1"], kind="object"), sources=owner.sources)])
    fragment = parse_surface_fragment("with classification from lc_classifier\n")
    check = classification_check(validate_surface_fragment_capabilities(fragment, base, graph=graph))
    if barrier is None:
        assert check.status is SurfaceCapabilityStatus.SUPPORTED
        compilation = compile_surface_fragment(fragment, base, graph=graph)
        run = plan_workflow(compilation.workflow, graph)
        assert run.steps[1].endpoint_plans[0].execution_reuse_from == EndpointPlanRef(step_index=0, plan_index=0)
    else:
        assert check.status is SurfaceCapabilityStatus.DEFERRED
        with pytest.raises(SurfaceLoweringError) as caught:
            compile_surface_fragment(fragment, base, graph=graph)
        assert caught.value.code == "deferred_capability"


def test_duplicate_continuation_checks_the_existing_emitted_occurrence(graph):
    surface = parse_surface_script(
        'objects from lsst via alerce\nwith classification from lc_classifier where best.class = "SN"\n'
    )
    base = lower_surface(surface).workflow
    base = WorkflowIR(steps=[*base.steps, FilterStep(predicate=base.steps[0].predicate)])
    fragment = parse_surface_fragment("with classification from lc_classifier\n")
    check = classification_check(validate_surface_fragment_capabilities(fragment, base, graph=graph))
    assert check.status is SurfaceCapabilityStatus.SUPPORTED
    assert compile_surface_fragment(fragment, base, graph=graph).workflow == base
