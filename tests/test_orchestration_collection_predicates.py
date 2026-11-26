"""Canonical collection nodes enforce context and never reach provider pushdown."""

import pytest
from pydantic import TypeAdapter, ValidationError

from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.data_layer.semantic_model import SemanticPathModel
from alertissimo.dsl.predicate_lowering import lower_expression_predicate
from alertissimo.orchestration.ir import FilterStep, Source, WorkflowIR
from alertissimo.orchestration.ir.predicates import (
    AggregateOperand, BooleanPredicate, ComparisonPredicate, ElementReference, ExistsPredicate,
    NotPredicate, Predicate, PredicateLiteral, QuantifierPredicate, SemanticReference,
    iter_semantic_references, predicate_requires_reference,
)
from alertissimo.orchestration.planner.predicate_realization import realize_predicate
from alertissimo.orchestration.validation import predicate_material_gaps, validate_step_capabilities


@pytest.fixture(scope="module")
def paths():
    return SemanticPathModel.from_ontology()


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def count():
    return AggregateOperand(function="count", reference=SemanticReference(
        semantic_type="lightcurve", field_path="points", producer="ztf", channel="fink"))


def comparison():
    return ComparisonPredicate(operator=">=", left=count(), right=PredicateLiteral(value=5))


@pytest.mark.parametrize("other", [
    SemanticReference(semantic_type="summary", field_path="detection_count"),
    PredicateLiteral(value=True), PredicateLiteral(value="5"), PredicateLiteral(value=float("inf")),
])
def test_aggregate_requires_a_finite_numeric_literal(other):
    for left, right in ((count(), other), (other, count())):
        with pytest.raises(ValidationError, match="numeric literal"):
            ComparisonPredicate(operator=">=", left=left, right=right)


def test_aggregate_is_not_an_exists_operand_or_standalone_predicate():
    with pytest.raises(ValidationError):
        ExistsPredicate(reference=count())
    with pytest.raises(ValidationError):
        TypeAdapter(Predicate).validate_python(count().model_dump())
    with pytest.raises(ValidationError):
        ComparisonPredicate(operator="=", left=count(), right=count())


def test_element_reference_outside_count_is_rejected_at_workflow_boundary():
    predicate = ComparisonPredicate(operator=">", left=ElementReference(field_path="time.mjd"),
                                    right=PredicateLiteral(value=60000))
    with pytest.raises(ValidationError, match="only valid inside a count"):
        WorkflowIR(steps=[FilterStep(predicate=predicate)])


def test_unbound_element_parameter_is_rejected_even_in_canonical_json():
    condition = ExistsPredicate(reference=ElementReference(field_path="photometry.{filter}.psf.mag"))
    aggregate = count().model_copy(update={"condition": condition})
    predicate = ComparisonPredicate(operator=">", left=aggregate, right=PredicateLiteral(value=0))
    raw = {"steps": [{"op": "filter", "predicate": predicate.model_dump(mode="json")}], "dsl_version": 2}
    import json
    with pytest.raises(ValidationError, match="unbound ontology parameter"):
        WorkflowIR.model_validate_json(json.dumps(raw))


@pytest.mark.parametrize("source", [
    "count(lightcurve.points where photometry.g.psf.mag exists) > 0",
    "min(lightcurve.points.photometry.g.psf.mag) < 19",
    "max(lightcurve.points.time.mjd) >= 60000",
    "for every {filter} in [g, r]: (count(lightcurve.points where photometry.{filter}.psf.mag exists) >= 5)",
    "for any {output}: (classification.assessment.{output}.probability >= 0.8)",
    "not (count(measurement@ztf:fink where quality.real_bogus >= 0.8) < 5)",
    "summary@ztf:fink.detection_count >= 1 and not (count(lightcurve.points) < 5)",
])
def test_all_collection_predicates_round_trip_and_are_version_two_only(source, paths):
    predicate = lower_expression_predicate(source, paths.record_types, origins=("ztf",))
    workflow = WorkflowIR(steps=[FilterStep(predicate=predicate, sources=[Source(origin="ztf")])])
    assert WorkflowIR.model_validate_json(workflow.model_dump_json()) == workflow
    adapter = TypeAdapter(Predicate)
    assert adapter.validate_json(adapter.dump_json(predicate)) == predicate
    assert predicate.model_config["frozen"]
    raw = workflow.model_dump(mode="json")
    raw["dsl_version"] = 1
    with pytest.raises(ValidationError, match="require dsl_version 2"):
        WorkflowIR.model_validate(raw)
    del raw["dsl_version"]
    with pytest.raises(ValidationError, match="require dsl_version 2"):
        WorkflowIR.model_validate(raw)


def test_new_nodes_are_frozen():
    for node, field, value in ((count(), "function", "max"),
                               (ElementReference(field_path="time.mjd"), "field_path", "position.ra"),
                               (QuantifierPredicate(quantifier="any", parameter="filter", operand=comparison()),
                                "quantifier", "every")):
        with pytest.raises(ValidationError, match="frozen"):
            setattr(node, field, value)


def test_quantifiers_reject_free_names_empty_duplicates_and_nonmembers(paths):
    for values in ((), ("g", "g")):
        with pytest.raises(ValidationError):
            QuantifierPredicate(quantifier="any", parameter="filter", values=values, operand=comparison())
    with pytest.raises(ValidationError):
        QuantifierPredicate(quantifier="any", parameter="band", operand=comparison())
    with pytest.raises(ValueError, match="members"):
        lower_expression_predicate("for any {filter} in [banana]: (min(lightcurve.points.photometry.{filter}.psf.mag) < 19)",
                                   paths.record_types, origins=("ztf",))


def test_every_output_requires_a_producer_even_in_canonical_ir(paths):
    with pytest.raises(ValueError, match="producer-qualified"):
        lower_expression_predicate("for every {output}: (classification.assessment.{output}.probability > 0.8)",
                                   paths.record_types)


def test_collection_dependency_does_not_invent_a_positive_scalar_assertion_witness():
    predicate = ComparisonPredicate(operator="=", left=count(), right=PredicateLiteral(value=0))
    assert list(iter_semantic_references(predicate)) == [count().reference]
    assert not predicate_requires_reference(predicate, count().reference)


def test_collection_predicate_is_never_realized_as_provider_parameters(graph, paths):
    predicate = lower_expression_predicate(
        "for any {output}: (classification.assessment.{output}.probability >= 0.8)", paths.record_types)
    count_predicate = comparison()
    for endpoint in graph.endpoint_capabilities:
        for node in (predicate, count_predicate, NotPredicate(operand=count_predicate)):
            realization = realize_predicate(node, endpoint=endpoint, graph=graph)
            assert not realization.params
            assert realization.pushdown is None
            assert realization.residual == node


def test_material_walker_understands_array_roots_and_element_leaves(graph, paths):
    predicate = lower_expression_predicate("count(lightcurve@ztf:fink.points where photometry.g.psf.mag exists) >= 5",
                                         paths.record_types)
    outputs = graph.fields_for_endpoint("fink", "ztf", "objects")
    assert predicate_material_gaps(predicate, outputs, broker="fink") == ()
    result = validate_step_capabilities(FilterStep(predicate=predicate), graph)
    assert result.status == "deferred"
    assert "collection admission is pending" in result.reason


@pytest.mark.parametrize("function,field", [
    ("count", "points.time.mjd"), ("min", "points"),
    ("max", "points.photometry.g.psf"), ("min", "time.last_mjd"),
])
def test_canonical_aggregate_reference_shape_is_checked(function, field):
    with pytest.raises(ValidationError):
        AggregateOperand(function=function, reference=SemanticReference(semantic_type="lightcurve", field_path=field))


def test_element_dependency_binds_to_the_innermost_aggregate():
    inner = AggregateOperand(function="count", reference=SemanticReference(
        semantic_type="lightcurve", field_path="forced_photometry_points"),
        condition=ExistsPredicate(reference=ElementReference(field_path="time.mjd")))
    outer = count().model_copy(update={"condition": ComparisonPredicate(
        operator=">", left=inner, right=PredicateLiteral(value=0))})
    predicate = ComparisonPredicate(operator=">", left=outer, right=PredicateLiteral(value=0))
    assert [ref.field_path for ref in iter_semantic_references(predicate)] == [
        "points", "forced_photometry_points", "forced_photometry_points.time.mjd"]
    WorkflowIR(steps=[FilterStep(predicate=predicate)])


def test_mixed_scalar_and_collection_pushdown_retains_the_collection(graph):
    from alertissimo.orchestration.ir.predicates import contains_collection_predicate
    scalar = ComparisonPredicate(operator=">=", left=SemanticReference(
        semantic_type="summary", field_path="time.last_mjd"), right=PredicateLiteral(value=60000))
    predicate = BooleanPredicate(operator="and", operands=(scalar, comparison()))
    for endpoint in graph.endpoint_capabilities:
        result = realize_predicate(predicate, endpoint=endpoint, graph=graph)
        assert not contains_collection_predicate(result.pushdown)
        assert contains_collection_predicate(result.residual)


def test_workflow_planning_cannot_bypass_the_local_filter_gate(graph):
    from alertissimo.orchestration.planner import PlanningDeferredError, plan_workflow
    workflow = WorkflowIR(steps=[FilterStep(predicate=comparison())])
    with pytest.raises(PlanningDeferredError, match="collection admission is pending"):
        plan_workflow(workflow, graph)
