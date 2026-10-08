"""Classification retrieval uses explicit targets and qualified mapping evidence."""

import shutil

import pytest
import yaml

from alertissimo.data_layer.execution import EndpointRegistry
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.orchestration.binding import bind_endpoint_calls
from alertissimo.orchestration.ir import (
    FilterStep, GetClassificationStep, LookupStep, SemanticSearchStep,
    Source, TargetSelector, WorkflowIR,
)
from alertissimo.orchestration.ir.predicates import (
    ComparisonPredicate, NotPredicate, PredicateLiteral, SemanticReference,
)
from alertissimo.orchestration.planner import (
    PlanningAmbiguityError, PlanningDeferredError, UnsupportedStepError,
    plan_step, plan_workflow,
)
from alertissimo.orchestration.runtime import CandidateInputRef, EndpointPlanRef, WorkflowRun
from alertissimo.orchestration.validation import validate_step_capabilities


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def classification(broker="alerce", origin="lsst", classifier=None, ids=("1", "2")):
    return GetClassificationStep(
        target=TargetSelector(ids=list(ids), kind="object") if ids is not None else None,
        classifier=classifier, sources=[Source(broker=broker, origin=origin)],
    )


def local_provider(tmp_path, broker="alerce", origin="lsst"):
    root = tmp_path / "providers"
    destination = root / broker / origin
    shutil.copytree(PROVIDERS_ROOT / broker / origin, destination)
    return root, destination


def edit_yaml(path, update):
    doc = yaml.safe_load(path.read_text())
    update(doc)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


@pytest.mark.parametrize("broker,origin,classifier,endpoint,physical,values", [
    ("alerce", "lsst", None, "query_probabilities", "oid", [1, 2]),
    ("alerce", "ztf", "lc_classifier", "query_probabilities", "oid", ["1", "2"]),
    ("fink", "ztf", "FINK", "objects", "objectId", ["1,2"]),
    ("lasair", "ztf", "tns", "objects", "objectIds", ["1,2"]),
    ("lasair", "lsst", "sherlock", "sherlock_object", "objectId", ["1,2"]),
])
def test_classification_recipes_preserve_target_encoding(
    graph, broker, origin, classifier, endpoint, physical, values,
):
    step = classification(broker, origin, classifier)
    plan, = plan_step(step, graph)
    assert plan.endpoint == endpoint
    assert plan.parameter_sources[physical] == ("target", "ids")
    calls = bind_endpoint_calls(step, plan, EndpointRegistry())
    assert [call.params[physical] for call in calls] == values
    if broker == "alerce" and origin == "ztf":
        assert plan.parameter_sources["classifier"] == ("classifier",)
        assert all(call.params["classifier"] == classifier for call in calls)
    else:
        assert all("classifier" not in call.params for call in calls)


def test_qualified_dynamic_retrieval_needs_an_authored_selector(graph):
    with pytest.raises(PlanningDeferredError, match="dynamic producer mapping"):
        plan_step(classification(classifier="lc_classifier"), graph)


def test_parameter_existence_does_not_replace_a_recipe_assignment(tmp_path):
    root, destination = local_provider(tmp_path)
    def add_selector(doc):
        endpoint = doc["endpoints"]["query_probabilities"]
        endpoint["params"]["classifier"] = {"type": "string"}
        endpoint["server_filters"].append("classifier")
    edit_yaml(destination / "endpoints.yaml", add_selector)
    with pytest.raises(PlanningDeferredError, match="declared server-filter translation"):
        plan_step(classification(classifier="lc_classifier"), build_capability_graph(root))


def test_authored_selector_needs_server_filter_evidence(tmp_path):
    root, destination = local_provider(tmp_path, origin="ztf")
    def remove_filter(doc):
        doc["endpoints"]["query_probabilities"]["server_filters"].remove("classifier")
    edit_yaml(destination / "endpoints.yaml", remove_filter)
    with pytest.raises(PlanningDeferredError, match="declared server-filter translation"):
        plan_step(classification(origin="ztf", classifier="lc_classifier"), build_capability_graph(root))


@pytest.mark.parametrize("broker,origin", [("fink", "ztf"), ("lasair", "lsst"), ("antares", "ztf")])
def test_unmapped_classifier_is_unsupported(graph, broker, origin):
    with pytest.raises(UnsupportedStepError):
        plan_step(classification(broker, origin, "unknown_model"), graph)


@pytest.mark.parametrize("broker,origin", [("alerce", "ztf"), ("fink", "lsst"), ("lasair", "ztf")])
def test_real_classification_alternatives_remain_ambiguous(graph, broker, origin):
    with pytest.raises(PlanningAmbiguityError):
        plan_step(classification(broker, origin), graph)


def test_search_and_position_endpoints_are_not_fresh_classification_retrievals(graph):
    for broker in ("alerce", "fink", "lasair"):
        for origin in ("ztf", "lsst"):
            result = validate_step_capabilities(classification(broker, origin, ids=None), graph)
            assert result.status == "supported"
            assert all("target_id" in endpoint.binding_roles for endpoint in result.candidates)
            assert all(source_result.recipes for source_result in result.source_results)


def test_classification_recipes_work_without_operation_tags(tmp_path):
    root, destination = local_provider(tmp_path)
    def remove_tags(doc):
        for endpoint in doc["endpoints"].values():
            endpoint["operation_types"] = []
    edit_yaml(destination / "endpoints.yaml", remove_tags)
    plan, = plan_step(classification(), build_capability_graph(root))
    assert plan.endpoint == "query_probabilities"


def test_unbound_recipe_does_not_fall_back_to_search_tags(tmp_path):
    root, destination = local_provider(tmp_path)
    def constant_identity(doc):
        doc["recipes"]["get_classification"][0]["calls"][0]["params"]["oid"] = {"value": 123}
    edit_yaml(destination / "capabilities.yaml", constant_identity)
    with pytest.raises(PlanningDeferredError, match="does not bind the target identities"):
        plan_step(classification(), build_capability_graph(root))


def test_duplicate_classification_recipes_remain_ambiguous(tmp_path):
    root, destination = local_provider(tmp_path)
    def duplicate(doc):
        alternatives = doc["recipes"]["get_classification"]
        alternatives.append(alternatives[0])
    edit_yaml(destination / "capabilities.yaml", duplicate)
    with pytest.raises(PlanningAmbiguityError, match=r"recipe\[1\]"):
        plan_step(classification(), build_capability_graph(root))


def test_targetless_classification_preserves_candidate_binding_after_json_round_trip(graph):
    get = classification(ids=None)
    workflow = WorkflowIR(steps=[
        LookupStep(target=TargetSelector(ids=["1", "2"], kind="object"), sources=get.sources),
        get,
    ])
    run = plan_workflow(workflow, graph)
    restored = WorkflowRun.model_validate_json(run.model_dump_json())
    assert restored == run
    plan, = restored.steps[1].endpoint_plans
    assert plan.candidate_input_from == CandidateInputRef(step_index=0)
    assert plan.execution_reuse_from is None
    assert plan.parameter_sources == {"oid": ("target", "ids")}
    calls = bind_endpoint_calls(get, plan, EndpointRegistry(), runtime_values={"target_id": ["1", "2"]})
    assert [call.params["oid"] for call in calls] == [1, 2]


def qualified_search(sources):
    return SemanticSearchStep(
        semantic_type="summary", sources=sources,
        predicate=ComparisonPredicate(
            left=SemanticReference(
                semantic_type="classification", producer="lc_classifier", field_path="best.class",
            ),
            operator="=", right=PredicateLiteral(value="SN"),
        ),
    )


def test_material_reuse_is_independent_of_provider_names(tmp_path):
    root, destination = local_provider(tmp_path)
    renamed = root / "example" / "survey"
    renamed.parent.mkdir()
    destination.rename(renamed)
    for filename in ("endpoints.yaml", "mappings.yaml", "capabilities.yaml"):
        def rename_provider(doc):
            doc.update(broker="example", origin="survey")
        edit_yaml(renamed / filename, rename_provider)
    get = classification("example", "survey", "lc_classifier", ids=None)
    run = plan_workflow(WorkflowIR(steps=[qualified_search(get.sources), get]), build_capability_graph(root))
    consumer, = run.steps[1].endpoint_plans
    assert consumer.endpoint == "query_objects"
    assert consumer.execution_reuse_from == EndpointPlanRef(step_index=0, plan_index=0)
    assert WorkflowRun.model_validate_json(run.model_dump_json()) == run


@pytest.mark.parametrize("changed_population", [False, True])
def test_dynamic_material_reuse_needs_a_positive_requirement_and_the_same_population(graph, changed_population):
    get = classification(classifier="lc_classifier", ids=None)
    search = qualified_search(get.sources)
    if changed_population:
        steps = [search, FilterStep(criteria={}), get]
    else:
        search = search.model_copy(update={"predicate": NotPredicate(operand=search.predicate)})
        steps = [search, get]
    with pytest.raises(PlanningDeferredError, match="dynamic producer mapping"):
        plan_workflow(WorkflowIR(steps=steps), graph)
