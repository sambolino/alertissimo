"""Required predicate inputs agree at recipe load, admission, and binding.

Provider changes here are temporary test contracts, not activated discovery APIs.
"""

from dataclasses import replace
import shutil

import pytest
import yaml

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import EndpointRegistry
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.runtime.capability_graph import CapabilityGraphError, build_capability_graph
from alertissimo.dsl import SurfaceLoweringError
from alertissimo.orchestration.binding import MissingBoundParameterError, bind_endpoint
from alertissimo.orchestration.ir import (
    BooleanPredicate, ComparisonPredicate, NotPredicate, PredicateLiteral,
    SemanticReference, SemanticSearchStep, Source,
)
from alertissimo.orchestration.planner import PlanningDeferredError, plan_step
from alertissimo.orchestration.runtime import EndpointPlan
from alertissimo.orchestration.validation import validate_step_capabilities


def edit_yaml(path, update):
    document = yaml.safe_load(path.read_text())
    update(document)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def provider(tmp_path, *, producer_binding=True, null_default=False):
    root = tmp_path / "providers"
    destination = root / "alerce" / "lsst"
    shutil.copytree(PROVIDERS_ROOT / "alerce" / "lsst", destination)

    def require_class(document):
        declaration = document["endpoints"]["query_objects"]["params"]["class_name"]
        declaration["required"] = True
        if null_default:
            declaration["default"] = None

    edit_yaml(destination / "endpoints.yaml", require_class)
    if not producer_binding:
        def remove_producer(document):
            document["predicate_bindings"]["query_objects"] = [
                item for item in document["predicate_bindings"]["query_objects"]
                if item["parameter"] != "classifier"
            ]
        edit_yaml(destination / "capabilities.yaml", remove_producer)
    return root, destination


def comparison(value="SN", operator="=", **qualifiers):
    return ComparisonPredicate(
        left=SemanticReference(semantic_type="classification", field_path="best.class", **qualifiers),
        operator=operator, right=PredicateLiteral(value=value),
    )


def search(predicate=None):
    return SemanticSearchStep(
        semantic_type="summary", sources=[Source(broker="alerce", origin="lsst")],
        predicate=predicate,
    )


@pytest.mark.parametrize("kind", ["plain", "qualified", "inverted", "repeated", "residual"])
def test_eligible_predicate_supplies_required_parameter_without_recipe_assignment(tmp_path, kind):
    root, _ = provider(tmp_path)
    graph = build_capability_graph(root)
    predicate = comparison()
    if kind == "qualified":
        predicate = comparison(producer="lc_classifier", channel="alerce")
    elif kind == "inverted":
        predicate = ComparisonPredicate(left=predicate.right, operator="=", right=predicate.left)
    elif kind == "repeated":
        predicate = BooleanPredicate(operator="and", operands=(predicate, predicate))
    elif kind == "residual":
        residual = ComparisonPredicate(
            left=SemanticReference(semantic_type="summary", field_path="position.ra"),
            operator=">", right=PredicateLiteral(value=100),
        )
        predicate = BooleanPredicate(operator="and", operands=(predicate, residual))
    step = search(predicate)
    recipe, = graph.query_recipes(broker="alerce", origin="lsst", op="semantic_search")
    assert recipe.calls[0].params == ()
    assert any(binding.parameter == "class_name" for binding in recipe.calls[0].predicate_bindings)
    assert validate_step_capabilities(step, graph).status == "supported"
    plan, = plan_step(step, graph)
    restored = EndpointPlan.model_validate_json(plan.model_dump_json())
    bound = bind_endpoint(step, restored, EndpointRegistry(root))
    expected = {"class_name": "SN"}
    if kind == "qualified":
        expected["classifier"] = "lc_classifier"
    assert bound.params == expected
    assert restored.predicate_realization.params == expected
    assert restored.predicate_realization.residual == (residual if kind == "residual" else None)


@pytest.mark.parametrize("kind", ["missing", "operator", "channel", "producer", "conflict", "or", "not"])
def test_ineligible_predicate_is_deferred_during_admission_not_at_network_access(tmp_path, kind):
    root, _ = provider(tmp_path, producer_binding=kind != "producer")
    graph = build_capability_graph(root)
    predicate = comparison()
    if kind == "missing":
        predicate = None
    elif kind == "operator":
        predicate = comparison(operator="!=")
    elif kind == "channel":
        predicate = comparison(channel="fink")
    elif kind == "producer":
        predicate = comparison(producer="lc_classifier")
    elif kind in {"conflict", "or"}:
        predicate = BooleanPredicate(
            operator="and" if kind == "conflict" else "or",
            operands=(predicate, comparison("AGN")),
        )
    else:
        predicate = NotPredicate(operand=predicate)
    step = search(predicate)
    result = validate_step_capabilities(step, graph)
    assert result.status == "deferred"
    assert result.candidates == ()
    assert "class_name" in result.source_results[0].reason
    assert "eligible predicate" in result.source_results[0].reason
    with pytest.raises(PlanningDeferredError, match="class_name"):
        plan_step(step, graph)


@pytest.mark.parametrize("condition", [
    None,
    'classification.best.class != "SN"',
    'classification@lc_classifier:fink.best.class = "SN"',
    'classification.best.class = "SN" and classification.best.class = "AGN"',
    'classification.best.class = "SN" or classification.best.class = "AGN"',
    'not (classification.best.class = "SN")',
])
def test_public_facade_refuses_unbound_required_inputs_without_calling_executor(tmp_path, condition):
    root, _ = provider(tmp_path)
    graph = build_capability_graph(root)
    source = "objects from lsst via alerce\n"
    if condition is not None:
        source += f"where {condition}\n"

    class NoCalls:
        calls = []

        def execute(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            raise AssertionError("provider must not be called")

    executor = NoCalls()
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert not validation.is_runnable
    with pytest.raises(SurfaceLoweringError):
        execute_dsl(source, graph=graph, registry=EndpointRegistry(root), executor=executor, continue_from=None)
    assert executor.calls == []


def test_public_validation_and_binder_agree_on_eligible_required_predicate(tmp_path):
    root, _ = provider(tmp_path)
    graph = build_capability_graph(root)
    source = 'objects from lsst via alerce\nwhere classification.best.class = "SN"\n'
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    step = validation.compilation.workflow.steps[0]
    plan, = plan_step(step, graph)
    assert bind_endpoint(step, plan, EndpointRegistry(root)).params == {"class_name": "SN"}


def test_required_declaration_without_any_assignment_or_predicate_binding_still_fails_load(tmp_path):
    root, destination = provider(tmp_path)

    def remove_class_binding(document):
        document["predicate_bindings"]["query_objects"] = [
            item for item in document["predicate_bindings"]["query_objects"]
            if item["parameter"] != "class_name"
        ]

    edit_yaml(destination / "capabilities.yaml", remove_class_binding)
    with pytest.raises(CapabilityGraphError, match="required parameter 'class_name'.*no assignment"):
        build_capability_graph(root)


def test_null_default_does_not_satisfy_required_predicate_input_in_any_phase(tmp_path):
    root, _ = provider(tmp_path, null_default=True)
    graph = build_capability_graph(root)
    assert validate_step_capabilities(search(), graph).status == "deferred"
    plan, = plan_step(search(comparison()), graph)
    unbound_plan = plan.model_copy(update={"predicate_realization": None})
    with pytest.raises(MissingBoundParameterError, match="class_name"):
        bind_endpoint(search(), unbound_plan, EndpointRegistry(root))
    assert bind_endpoint(search(comparison()), plan, EndpointRegistry(root)).params == {"class_name": "SN"}


def test_only_the_discovery_call_may_use_required_predicate_parameters(tmp_path):
    root, destination = provider(tmp_path)

    def require_on_get(document):
        endpoint = document["endpoints"]["query_probabilities"]
        endpoint["params"]["class_name"] = {"type": "string", "required": True}
        endpoint["server_filters"].append("class_name")

    def add_binding(document):
        document["predicate_bindings"]["query_probabilities"] = [{
            "path": "classification.assessment.{output}.class", "operator": "=", "parameter": "class_name",
        }]

    edit_yaml(destination / "endpoints.yaml", require_on_get)
    edit_yaml(destination / "capabilities.yaml", add_binding)
    with pytest.raises(CapabilityGraphError, match="required parameter 'class_name'.*no assignment"):
        build_capability_graph(root)


def test_missing_required_predicate_cannot_fall_back_to_legacy_tags(tmp_path):
    root, _ = provider(tmp_path)
    graph = build_capability_graph(root)
    endpoints = tuple(replace(endpoint, operation_types=("object_search",))
                      if endpoint.endpoint == "query_objects" else endpoint
                      for endpoint in graph.endpoint_capabilities)
    graph = replace(graph, endpoint_capabilities=endpoints)
    with pytest.raises(PlanningDeferredError, match="class_name"):
        plan_step(search(), graph)
