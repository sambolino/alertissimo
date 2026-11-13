"""Bounded discovery retrieves all requested broker assertions before selection."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from itertools import count

import pytest

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import SurfaceLoweringError
from alertissimo.dsl.predicate_lowering import lower_expression_predicate
from alertissimo.orchestration.ir import WorkflowIR
from alertissimo.orchestration.normalization import normalize_workflow_execution, summary_object_identity
from alertissimo.orchestration.planner import PlanningDeferredError
from alertissimo.orchestration.runtime import WorkflowExecutionError


IDS = tuple(f"ZTF20{letter * 7}" for letter in "abcd")
CONE = "objects from ztf via alerce\ninside (124.88, -6.02, 5arcsec)\n"
# query_probabilities maps class-specific assessments, not a synthesized best.
ALABEL = "classification@lc_classifier:alerce.assessment.snia.class"
APROB = "classification@lc_classifier:alerce.assessment.snia.probability"
FLABEL = "classification@fink:fink.best.class"
FSCORE = "classification@fink:fink.assessment.sn_vs_all.probability"
SUMMARY = "summary@ztf:alerce.detection_count"
CONDITION = f'({ALABEL} = "SNIa" and {APROB} >= 0.8) or ({FLABEL} = "SN candidate" and {FSCORE} >= 0.8)'
NOW = datetime(1858, 11, 17, tzinfo=timezone.utc) + timedelta(days=58005)


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def identities(portfolios):
    return [summary_object_identity(portfolio)[1] for portfolio in portfolios]


def program(requirements="with classification via alerce, fink\n", *, condition=CONDITION, latest=None, timed=False, spatial=True):
    selection = "" if latest is None else f"latest {latest}\n"
    window = "first within 10d\n" if timed else ""
    discovery = CONE if spatial else "objects from ztf via alerce\n"
    return discovery + window + selection + requirements + f"where {condition}\n"


class Executor:
    def __init__(self, *, empty=None, fail=None, discovery_classification=False):
        self.calls, self.ids = [], count()
        self.empty, self.fail = empty, fail
        self.discovery_classification = discovery_classification

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        params = deepcopy(dict(params or {}))
        self.calls.append((broker, endpoint, params))
        assert origin == "ztf"
        if (broker, endpoint) == ("alerce", "query_objects"):
            assert not {"class_name", "probability"} & params.keys()
            # Targeted selected-summary calls are enrichment, not discovery
            # pushdown of the cross-broker initial condition.
            if "oid" in params:
                assert params["oid"] in IDS
                assert params["classifier"] in {"lc_classifier", "stamp_classifier"}
            else:
                assert "classifier" not in params
            payload = {"items": [{"oid": oid, "meanra": 124.88, "meandec": -6.02,
                                  "firstmjd": 58000, "lastmjd": 61004 - i,
                                  "ndet": (10, 1, 10, None)[i]} for i, oid in enumerate(IDS)]}
            if self.discovery_classification:
                # best.* is mapped from object-search rows when supplied there.
                for row in payload["items"][:3]:
                    row.update(classifier="lc_classifier", probability=0.95,
                               **{"class": "AGN" if row["oid"] == IDS[1] else "SNIa"})
            if "oid" in params:
                payload["items"] = [row for row in payload["items"] if row["oid"] == params["oid"]]
                if self.empty == broker:
                    payload["items"] = []
        elif (broker, endpoint) == ("alerce", "query_probabilities"):
            if self.fail == broker:
                raise RuntimeError("alerce classification unavailable")
            oid = params["oid"]
            payload = [] if self.empty == broker or oid == IDS[3] else [{
                "classifier_name": "lc_classifier", "classifier_version": "v1", "ranking": 1,
                "class_name": "AGN" if oid == IDS[1] else "SNIa",
                "probability": 0.2 if oid == IDS[2] else 0.95,
            }]
        else:
            assert (broker, endpoint) == ("fink", "objects")
            if self.fail == broker:
                raise RuntimeError("fink classification unavailable")
            payload = [] if self.empty == broker else [
                {"i:objectId": oid, "i:candid": 1000 + IDS.index(oid) * 10 + point,
                 "i:jd": 2462000.5 + point, "i:fid": 1, "i:magpsf": 19.0,
                 "i:sigmapsf": 0.1, "i:ra": 124.88, "i:dec": -6.02,
                 "i:ndethist": 50, "i:jdendhist": 2465000.5,
                 **({} if oid == IDS[3] else {"v:classification": "SN candidate" if oid == IDS[1] else "AGN",
                                             "d:snn_sn_vs_all": 0.95})}
                for oid in params["objectId"].split(",") for point in range(2)
            ]
        return ExecutionResult(payload=payload, execution_provenance=InternalExecutionProvenance(
            internal_execution_id=InternalExecutionId(f"multi-cone:{next(self.ids)}"),
            broker=broker, origin=origin, endpoint=endpoint, params=params,
        ))


@pytest.mark.parametrize("requirements", [
    "with classification via alerce, fink\n",
    "with classification via fink, alerce\n",
    "with classification via alerce\nwith classification via fink\n",
    "with classification from lc_classifier via alerce\nwith classification from fink via fink\n",
    "",  # Both qualified channels imply their existing targeted Gets.
])
@pytest.mark.parametrize("temporal_only", [False, True])
def test_all_initial_broker_evidence_arrives_before_whole_predicate_evaluation(graph, requirements, temporal_only):
    source = program(requirements, timed=temporal_only, spatial=not temporal_only)
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    executor = Executor()
    result = execute_dsl(source, graph=graph, executor=executor, continue_from=None, reference_time=NOW)
    assert [step.op for step in result.workflow.steps] == [
        "semantic_search" if temporal_only else "cone_search", "get_classification", "get_classification", "filter",
    ]
    assert result.workflow.steps[0].predicate is None
    assert result.workflow.steps[-1].predicate == lower_expression_predicate(CONDITION, frozenset({"classification"}))
    assert identities(result.portfolios) == list(IDS[:2])
    assert all(identities(view.portfolios) == list(IDS) for view in result.result.steps[:3])
    # Discovery, four probability calls, eight selected summaries, one Fink batch.
    assert len(executor.calls) == 14
    summaries = [params for _, name, params in executor.calls if name == "query_objects" and "oid" in params]
    assert {(p["oid"], p["classifier"]) for p in summaries} == {
        (oid, method) for oid in IDS for method in ("lc_classifier", "stamp_classifier")
    }
    assert {params["oid"] for _, name, params in executor.calls if name == "query_probabilities"} == set(IDS)
    assert next(params for broker, _, params in executor.calls if broker == "fink")["objectId"] == ",".join(IDS)
    assert all(plan.execution_reuse_from is None for step in result.run.steps[1:3] for plan in step.endpoint_plans)
    # Assertions keep their own execution-local method/channel, with full measurements.
    assert any(record.semantic_type == "classification@lc_classifier:alerce" for record in result.portfolios[0].records)
    assert sum(record.semantic_type == "measurement@ztf:fink" for portfolio in result.portfolios for record in portfolio.records) == 4
    assert identities(normalize_workflow_execution(result.staged.execution).steps[-1].portfolios) == list(IDS[:2])
    assert WorkflowIR.model_validate_json(result.workflow.model_dump_json()) == result.workflow


def test_explicit_cross_broker_and_is_not_changed_to_or_or_quorum(graph):
    condition = f'{ALABEL} = "SNIa" and {FLABEL} = "SN candidate"'
    result = execute_dsl(program(condition=condition), graph=graph, executor=Executor(), continue_from=None)
    assert result.portfolios == ()  # The brokers disagree in this fixture.
    assert result.workflow.steps[-1].predicate.operator == "and"


@pytest.mark.parametrize("assessment,expected", [("snia", [IDS[0], IDS[2]]), ("agn", [IDS[1]])])
def test_explicit_label_comparison_uses_both_qualified_assertions(graph, assessment, expected):
    label = f"classification@lc_classifier:alerce.assessment.{assessment}.class"
    result = execute_dsl(program(condition=f"{label} != {FLABEL}"), graph=graph,
                         executor=Executor(), continue_from=None)
    assert identities(result.portfolios) == expected
    # This compares the supplied labels literally; no taxonomy or winner is inferred.
    assert result.workflow.steps[-1].predicate.right.semantic_type == "classification"


def test_scoped_broker_list_keeps_its_existing_whole_condition_or_semantics(graph):
    source = CONE + 'with classification via alerce, fink where best.class = "SNIa" or best.class = "SN candidate"\n'
    result = execute_dsl(source, graph=graph, executor=Executor(discovery_classification=True), continue_from=None)
    assert identities(result.portfolios) == list(IDS[:3])
    assert result.workflow.steps[-1].predicate.operator == "or"


@pytest.mark.parametrize("empty,expected", [("alerce", [IDS[1]]), ("fink", [IDS[0]])])
def test_successful_empty_broker_material_is_unknown_not_an_automatic_veto(graph, empty, expected):
    result = execute_dsl(program(), graph=graph, executor=Executor(empty=empty), continue_from=None)
    assert identities(result.portfolios) == expected


@pytest.mark.parametrize("fail", ["alerce", "fink"])
def test_required_broker_failure_does_not_drop_that_member_and_report_success(graph, fail):
    with pytest.raises(WorkflowExecutionError, match=f"{fail} classification unavailable"):
        execute_dsl(program(), graph=graph, executor=Executor(fail=fail), continue_from=None)


@pytest.mark.parametrize("timed,spatial", [(False, True), (True, True), (True, False)])
def test_latest_and_continuation_follow_all_material_without_refill(graph, timed, spatial):
    executor = Executor()
    first = execute_dsl(program(latest=1, timed=timed, spatial=spatial), graph=graph, executor=executor,
                        continue_from=None, reference_time=NOW)
    assert identities(first.portfolios) == [IDS[0]]
    assert first.workflow.steps[0].selection.after_step == 3
    snapshot, before = first.to_dict(), deepcopy(executor.calls)
    second = execute_dsl("with lightcurve via fink\n", graph=graph, executor=executor,
                         continue_from=first, reference_time=NOW + timedelta(days=20))
    assert executor.calls[:-1] == before
    assert executor.calls[-1][2] == {"objectId": IDS[0]}
    old_calls = deepcopy(executor.calls)
    third = execute_dsl(f"filter {SUMMARY} <= 2\nwith lightcurve via fink\n", graph=graph, executor=executor,
                        continue_from=second, reference_time=NOW + timedelta(days=40))
    assert third.portfolios == ()  # B would match, but was outside the original latest 1.
    assert executor.calls == old_calls
    assert first.to_dict() == snapshot
    assert third.workflow.steps[:len(second.workflow.steps)] == second.workflow.steps
    if timed:
        assert third.run.steps[0].time_reference == NOW
        assert executor.calls[0][2]["firstmjd"] == [57995.0, 58005.0]


@pytest.mark.parametrize("temporal_only", [False, True])
def test_summary_condition_can_join_the_multi_broker_expression(graph, temporal_only):
    condition = f"{SUMMARY} >= 5 and ({CONDITION})"
    result = execute_dsl(program(condition=condition, timed=temporal_only, spatial=not temporal_only),
                         graph=graph, executor=Executor(), continue_from=None, reference_time=NOW)
    assert identities(result.portfolios) == [IDS[0]]


def test_request_after_a_later_filter_cannot_delay_initial_implied_evidence(graph):
    source = (program("with classification via alerce\n")
              + f"filter {SUMMARY} >= 1\nwith classification via fink\n")
    executor = Executor()
    result = execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    assert result.workflow.steps[2].op == "get_classification"
    assert result.workflow.steps[2].sources[0].broker == "fink"
    assert result.workflow.steps[3].op == "filter"
    first_fink = next(params for broker, _, params in executor.calls if broker == "fink")
    assert first_fink["objectId"] == ",".join(IDS)
    assert identities(result.portfolios) == list(IDS[:2])


def test_unmapped_field_at_one_broker_cannot_borrow_another_brokers_probability(graph):
    source = CONE + 'with classification via alerce, fink where best.class = "SNIa" and best.probability >= 0.8\n'
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_valid and not validation.is_runnable
    executor = Executor()
    with pytest.raises(SurfaceLoweringError, match="unmapped.*best.probability"):
        execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    assert executor.calls == []


@pytest.mark.parametrize("requirements", [
    "",  # Several implicit named Gets at ALeRCE would erase each other's models.
    "with classification via fink\n",  # A generic request at Fink cannot fix that.
    "with classification via alerce\nwith classification from lc_classifier via alerce\n",
])
def test_conflicting_model_selection_within_one_broker_remains_guarded(graph, requirements):
    condition = f'{ALABEL} = "SNIa" and classification@stamp_classifier:alerce.best.class = "SN" and {FLABEL} = "SN candidate"'
    source = program(requirements, condition=condition)
    assert not validate_dsl(source, graph=graph, continue_from=None).is_runnable
    executor = Executor()
    with pytest.raises((SurfaceLoweringError, PlanningDeferredError)):
        execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    assert executor.calls == []
