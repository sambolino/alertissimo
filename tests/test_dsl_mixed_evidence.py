"""Whole initial Boolean conditions over required summary/classification material."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from itertools import count

import pytest

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.data_layer.runtime.recipes import ConstantValueSource
from alertissimo.dsl import SurfaceLoweringError
from alertissimo.dsl.predicate_lowering import lower_expression_predicate
from alertissimo.orchestration.ir import WorkflowIR
from alertissimo.orchestration.normalization import normalize_workflow_execution, summary_object_identity
from alertissimo.orchestration.planner import PlanningDeferredError


IDS = tuple(f"ZTF20{letter * 7}" for letter in "abcd")
SUMMARY = "summary@ztf:alerce.detection_count"
LABEL = "classification@fink:fink.best.class"
PROB = "classification@fink:fink.assessment.sn_vs_all.probability"
COUNTS = (10, 10, 1, None)
CONE = "objects from ztf via alerce\ninside (124.88, -6.02, 5arcsec)\n"


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def identities(portfolios):
    return [summary_object_identity(portfolio)[1] for portfolio in portfolios]


def program(condition, *, latest=None, requirement_first=True, inline=False, broker="alerce"):
    selection = "" if latest is None else f"latest {latest}\n"
    requirement = "with classification via fink\n"
    if inline:
        clauses = f"with classification via fink where {condition}\n"
    else:
        where = f"where {condition}\n"
        clauses = requirement + where if requirement_first else where + requirement
    return CONE.replace("via alerce", f"via {broker}") + selection + clauses


class Executor:
    def __init__(self):
        self.calls, self.ids = [], count()

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        params = deepcopy(dict(params or {}))
        self.calls.append((broker, endpoint, params))
        assert origin == "ztf"
        if (broker, endpoint) == ("alerce", "query_objects"):
            # No native partial predicate may prune either side of the OR.
            assert not {"ndet", "n_det", "class_name", "classifier", "probability"} & params.keys()
            payload = {"items": [
                {"oid": oid, "meanra": 124.88, "meandec": -6.02,
                 "firstmjd": 58000, "lastmjd": 61005 - index, "ndet": COUNTS[index]}
                for index, oid in enumerate(IDS)
            ]}
        elif (broker, endpoint) == ("lasair", "cone"):
            payload = [{"object": oid, "separation": 1.0} for oid in IDS]
        elif (broker, endpoint) == ("lasair", "query"):
            payload = [{"objectId": oid, "ramean": 124.88, "decmean": -6.02,
                        "ncand": COUNTS[index], "jdmin": 2458000.5, "jdmax": 2461005.5 - index}
                       for index, oid in enumerate(IDS)]
        else:
            assert (broker, endpoint) == ("fink", "objects")
            payload = []
            for oid in params["objectId"].split(","):
                for point in range(2):
                    label = "SN candidate" if oid == IDS[1] or oid == IDS[0] and point == 0 else "AGN"
                    probability = 0.2 if oid == IDS[0] and point == 0 else 0.99
                    assertion = {} if oid == IDS[3] else {"v:classification": label, "d:snn_sn_vs_all": probability}
                    payload.append({"i:objectId": oid, "i:candid": 1000 + IDS.index(oid) * 10 + point,
                                    "i:jd": 2462000.5 + point, "i:fid": 1, "i:magpsf": 19.0,
                                    "i:sigmapsf": 0.1, "i:ra": 124.88, "i:dec": -6.02,
                                    "i:ndethist": 50, "i:jdendhist": 2465000.5, **assertion})
        return ExecutionResult(payload=payload, execution_provenance=InternalExecutionProvenance(
            internal_execution_id=InternalExecutionId(f"mixed:{next(self.ids)}"),
            broker=broker, origin=origin, endpoint=endpoint, params=params,
        ))


@pytest.mark.parametrize("condition,expected", [
    (f'{SUMMARY} >= 5 and ({LABEL} = "SN candidate" and {PROB} >= 0.8)', [IDS[1]]),
    (f'{SUMMARY} <= 2 or ({LABEL} = "SN candidate" and {PROB} >= 0.8)', [IDS[1], IDS[2]]),
    (f'not ({SUMMARY} >= 5 or {LABEL} = "SN candidate")', [IDS[2]]),
    (f'({SUMMARY} >= 5 and {LABEL} = "SN candidate") and {PROB} >= 0.8', [IDS[1]]),
])
@pytest.mark.parametrize("requirement_first", [False, True])
def test_full_mixed_expression_is_preserved_and_evaluated_after_retrieval(graph, condition, expected, requirement_first):
    source = program(condition, requirement_first=requirement_first)
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    executor = Executor()
    result = execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    assert [step.op for step in result.workflow.steps] == ["cone_search", "get_classification", "filter"]
    assert result.workflow.steps[0].predicate is None
    assert result.workflow.steps[2].predicate == lower_expression_predicate(condition, frozenset({"summary", "classification"}))
    assert identities(result.result.steps[0].portfolios) == list(IDS)
    assert identities(result.result.steps[1].portfolios) == list(IDS)
    assert identities(result.portfolios) == expected
    assert [name for _, name, _ in executor.calls] == ["query_objects", "objects"]
    assert executor.calls[-1][2] == {"objectId": ",".join(IDS)}
    assert sum(r.semantic_type == "measurement@ztf:fink" for p in result.portfolios for r in p.records) == 2 * len(expected)
    assert identities(normalize_workflow_execution(result.staged.execution).steps[2].portfolios) == expected
    assert WorkflowIR.model_validate_json(result.workflow.model_dump_json()) == result.workflow


def test_inline_mixed_predicate_keeps_summary_qualification_and_assertion_correlation(graph):
    condition = f'{SUMMARY} >= 5 and best.class = "SN candidate" and assessment.sn_vs_all.probability >= 0.8'
    result = execute_dsl(program(condition, inline=True), graph=graph, executor=Executor(), continue_from=None)
    # A has an SN/low and AGN/high assertion, despite enough reported detections.
    assert identities(result.portfolios) == [IDS[1]]


def test_named_classifier_does_not_treat_summary_origin_as_another_model(graph):
    condition = f'{SUMMARY} >= 5 and {LABEL} = "SN candidate" and {PROB} >= 0.8'
    source = program(condition).replace("classification via fink", "classification from fink via fink")
    result = execute_dsl(source, graph=graph, executor=Executor(), continue_from=None)
    assert identities(result.portfolios) == [IDS[1]]


def test_initial_condition_matches_explicit_retrieval_and_continuation_filter(graph):
    condition = f'{SUMMARY} <= 2 or ({LABEL} = "SN candidate" and {PROB} >= 0.8)'
    fresh = execute_dsl(program(condition), graph=graph, executor=Executor(), continue_from=None)
    executor = Executor()
    base = execute_dsl(CONE, graph=graph, executor=executor, continue_from=None)
    snapshot = base.to_dict()
    continued = execute_dsl(f"with classification via fink\nfilter {condition}\n",
                            graph=graph, executor=executor, continue_from=base)
    assert identities(fresh.portfolios) == identities(continued.portfolios) == [IDS[1], IDS[2]]
    assert [name for _, name, _ in executor.calls] == ["query_objects", "objects"]
    assert base.to_dict() == snapshot


@pytest.mark.parametrize("summary,expected", [
    ("summary.detection_count", [IDS[1]]), (SUMMARY, []),
])
def test_unqualified_summary_keeps_existing_any_matching_record_semantics(graph, summary, expected):
    source = program(f'{summary} >= 20 and {LABEL} = "SN candidate" and {PROB} >= 0.8')
    result = execute_dsl(source, graph=graph, executor=Executor(), continue_from=None)
    # Fink reports 50; ALeRCE reports <=10. Qualification determines the assertion.
    assert identities(result.portfolios) == expected


def test_whole_or_runs_before_latest_and_continuation_never_refills_it(graph):
    condition = f'{SUMMARY} <= 2 or ({LABEL} = "SN candidate" and {PROB} >= 0.8)'
    executor = Executor()
    first = execute_dsl(program(condition, latest=1), graph=graph, executor=executor, continue_from=None)
    assert identities(first.portfolios) == [IDS[1]]
    assert first.workflow.steps[0].selection.after_step == 2
    snapshot = first.to_dict()
    second = execute_dsl("with lightcurve via fink\n", graph=graph, executor=executor, continue_from=first)
    assert executor.calls[-1][2] == {"objectId": IDS[1]}
    previous_calls = deepcopy(executor.calls)
    third = execute_dsl(f"filter {SUMMARY} <= 2\nwith lightcurve via fink\n",
                        graph=graph, executor=executor, continue_from=second)
    assert third.portfolios == ()  # C was initially eligible; do not refill B.
    assert executor.calls == previous_calls
    assert first.to_dict() == snapshot
    assert second.workflow.steps[:len(first.workflow.steps)] == first.workflow.steps
    assert third.workflow.steps[:len(second.workflow.steps)] == second.workflow.steps


def test_mixed_condition_composes_with_existing_time_and_latest_boundaries(graph):
    condition = f'{SUMMARY} <= 2 or ({LABEL} = "SN candidate" and {PROB} >= 0.8)'
    source = program(condition, latest=2).replace("latest 2\n", "first within 10d\nlatest 2\n")
    reference = datetime(1858, 11, 17, tzinfo=timezone.utc) + timedelta(days=58005)
    executor = Executor()
    result = execute_dsl(source, graph=graph, executor=executor, continue_from=None, reference_time=reference)
    assert identities(result.portfolios) == [IDS[1], IDS[2]]
    assert result.run.steps[0].time_reference == reference
    assert result.workflow.steps[0].selection.after_step == 2
    assert executor.calls[0][2]["firstmjd"] == [57995.0, 58005.0]


def test_composite_discovery_can_supply_required_summary_fields(graph):
    condition = f'summary@ztf:lasair.detection_count >= 5 and {LABEL} = "SN candidate" and {PROB} >= 0.8'
    executor = Executor()
    result = execute_dsl(program(condition, latest=1, broker="lasair"), graph=graph, executor=executor, continue_from=None)
    assert identities(result.portfolios) == [IDS[1]]
    assert result.run.steps[0].endpoint_plans[1].required
    assert [name for _, name, _ in executor.calls] == ["cone", "query", "objects"]


@pytest.mark.parametrize("change", ["optional", "projection"])
def test_optional_or_unprojected_summary_cannot_establish_mixed_admission(graph, change):
    altered = graph
    if change == "projection":
        recipes = []
        for recipe in graph.recipe_capabilities:
            if (recipe.broker, recipe.origin, recipe.op) == ("lasair", "ztf", "cone_search"):
                calls = []
                for call in recipe.calls:
                    params = tuple(replace(param, source=ConstantValueSource(param.source.value.replace("objects.ncand,", "")))
                                   if call.endpoint == "query" and param.parameter == "selected" else param
                                   for param in call.params)
                    calls.append(replace(call, params=params))
                recipe = replace(recipe, calls=tuple(calls))
            recipes.append(recipe)
        altered = replace(graph, recipe_capabilities=tuple(recipes))
    condition = f'summary@ztf:lasair.detection_count >= 5 and {LABEL} = "SN candidate"'
    source = program(condition, broker="lasair", latest=1 if change == "projection" else None)
    validation = validate_dsl(source, graph=altered, continue_from=None)
    assert validation.is_valid and not validation.is_runnable
    executor = Executor()
    with pytest.raises(SurfaceLoweringError, match="unmapped.*required discovery"):
        execute_dsl(source, graph=altered, executor=executor, continue_from=None)
    assert executor.calls == []


def test_legacy_classifier_producer_does_not_borrow_another_calls_broker(graph):
    field = next(field for field in graph.fields_for_endpoint("fink", "ztf", "objects")
                 if field.semantic_record_type == "classification@fink" and field.relative_field_path == "best.class")
    borrowed = replace(field, broker="alerce", endpoint="query_objects", semantic_record_type="classification@fink",
                       semantic_path="classification@fink.best.probability", relative_field_path="best.probability")
    recipes = tuple(replace(recipe, calls=(replace(recipe.calls[0], outputs=recipe.calls[0].outputs + (borrowed,)),)
                           + recipe.calls[1:])
                    if (recipe.broker, recipe.origin, recipe.op) == ("alerce", "ztf", "cone_search") else recipe
                    for recipe in graph.recipe_capabilities)
    altered = replace(graph, recipe_capabilities=recipes)
    source = program(f"{SUMMARY} >= 5 and classification@fink:fink.best.probability >= 0.8")
    executor = Executor()
    with pytest.raises(SurfaceLoweringError, match="unmapped.*best.probability"):
        execute_dsl(source, graph=altered, executor=executor, continue_from=None)
    assert executor.calls == []


@pytest.mark.parametrize("condition", [
    f'{LABEL} = "SN candidate" and classification@lc_classifier.best.class = "SN"',
    f'{LABEL} = "SN candidate" and measurement@ztf:fink.quality.real_bogus >= 0.9',
])
def test_unqualified_classification_channels_and_measurement_dependencies_stay_deferred(graph, condition):
    source = program(condition)
    assert not validate_dsl(source, graph=graph, continue_from=None).is_runnable
    executor = Executor()
    with pytest.raises((SurfaceLoweringError, PlanningDeferredError)):
        execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    assert executor.calls == []
