"""Confirmation retains the authored proposition through material and layout."""

from collections import Counter
from copy import deepcopy
from itertools import count
import json

import pytest

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import SurfaceLoweringError, lower_surface, parse_surface_script
from alertissimo.dsl.predicate_lowering import lower_expression_predicate
from alertissimo.orchestration.ir import ConfirmStep, WorkflowIR
from alertissimo.orchestration.local_semantics import finalize_local_semantics
from alertissimo.orchestration.normalization import normalize_workflow_execution, summary_object_identity
from alertissimo.orchestration.runtime import WorkflowExecutionError


IDS = tuple(f"ZTF20{letter * 7}" for letter in "abcd")
LOOKUP = f"objects {', '.join(IDS)} from ztf via alerce\n"
CONDITION = 'classification.best.class = "SN"'
SCOPED = ('with classification from fink via fink where best.class = "SN" '
          'and assessment.sn_vs_all.probability >= 0.8\n')
QUALIFIED = ('classification@fink:fink.best.class = "SN" '
             'and classification@fink:fink.assessment.sn_vs_all.probability >= 0.8')


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def identities(portfolios):
    return [summary_object_identity(portfolio)[1] for portfolio in portfolios]


class Executor:
    def __init__(self, *, fail=None):
        self.calls, self.ids = [], count()
        self.fail = fail

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        params = deepcopy(dict(params or {}))
        self.calls.append((broker, endpoint, params))
        assert origin == "ztf"
        if broker == self.fail:
            raise RuntimeError(f"{broker} evidence unavailable")
        if (broker, endpoint) == ("alerce", "query_object"):
            # All incoming candidates already have a matching assertion. It
            # must never substitute for this Confirm's own broker evidence.
            payload = {"oid": params["oid"], "meanra": 120.0, "meandec": -6.0, "ndet": 2,
                       "firstmjd": 59000, "lastmjd": 59002,
                       "classifier": "lc_classifier", "class": "SN", "probability": 0.99}
        elif (broker, endpoint) == ("fink", "objects"):
            payload = [
                {"i:objectId": oid, "i:candid": 1000 + IDS.index(oid) * 10 + point,
                 "i:jd": 2459000.5 + point, "i:fid": 1, "i:magpsf": 19.0, "i:sigmapsf": 0.1,
                 "i:ndethist": 2, "i:ra": 120.0, "i:dec": -6.0,
                 **({} if oid == IDS[3] else {"v:classification": "other" if oid == IDS[2] else "SN",
                                             "d:snn_sn_vs_all": 0.2 if oid == IDS[1] else 0.95})}
                for oid in params["objectId"].split(",") for point in range(2)
            ]
        else:
            assert (broker, endpoint) == ("lasair", "objects")
            payload = [{"objectId": oid,
                        "objectData": {"ncand": 2, "jdmin": 2459000.5, "jdmax": 2459002.5,
                                       "ramean": 120.0, "decmean": -6.0},
                        "sherlock": {} if oid == IDS[3] else {
                            "classification": "other" if oid == IDS[1] else "SN",
                            "classificationReliability": 2},
                        "candidates": []}
                       for oid in params["objectIds"].split(",")]
        return ExecutionResult(payload=payload, execution_provenance=InternalExecutionProvenance(
            internal_execution_id=InternalExecutionId(f"confirm-scope:{next(self.ids)}"),
            broker=broker, origin=origin, endpoint=endpoint, params=params,
        ))


@pytest.mark.parametrize("gap", [
    "", "\n    \n",
    "with lightcurve via fink\n", "with classification via fink\n",
    "with classification via fink\nwith lightcurve via fink\n",
    "order by summary.detection_count desc\n",
])
def test_general_proposition_survives_layout_and_material_and_counts_distinct_brokers(graph, gap):
    source = LOOKUP + f"where {CONDITION}\n" + gap + "confirm by 2 via fink, lasair\n"
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    executor = Executor()
    result = execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    confirm = result.workflow.steps[-1]
    assert confirm.predicate == lower_expression_predicate(CONDITION, frozenset({"classification"}))
    assert identities(result.portfolios) == [IDS[0]]
    # B's two matching Fink rows are one vote; C has only Lasair's vote. D's
    # incoming ALeRCE class cannot fill either missing occurrence-local class.
    assert not any(endpoint == "query_probabilities" for _, endpoint, _ in executor.calls)
    assert sum(r.semantic_type == "measurement@ztf:fink" for r in result.portfolios[0].records) >= 2
    replayed = finalize_local_semantics(normalize_workflow_execution(result.staged.execution))
    assert identities(replayed.steps[-1].portfolios) == [IDS[0]]
    assert WorkflowIR.model_validate_json(result.workflow.model_dump_json()) == result.workflow


@pytest.mark.parametrize("quorum,expected", [(1, [IDS[1], IDS[2]]), (2, [])])
def test_missing_class_stays_unknown_under_negation_in_attached_proposition(graph, quorum, expected):
    source = LOOKUP + f'where not ({CONDITION})\nwith lightcurve via fink\nconfirm by {quorum} via fink, lasair\n'
    result = execute_dsl(source, graph=graph, executor=Executor(), continue_from=None)
    assert identities(result.portfolios) == expected


def scientific_records(portfolios):
    def native_signature(portfolio, record):
        source = record.internal_source
        assert source is not None
        execution = portfolio.execution(source.internal_execution_id)
        return (summary_object_identity(portfolio), record.semantic_type,
                json.dumps(dict(record.fields), sort_keys=True), execution.broker,
                execution.endpoint, source.payload_key, source.payload_path, source.payload_index)

    signatures = []
    for portfolio in portfolios:
        native = {r.internal_record_id.value: native_signature(portfolio, r)
                  for r in portfolio.records if r.internal_source is not None}
        for record in portfolio.records:
            if record.internal_source is not None:
                signatures.append(native[record.internal_record_id.value])
                continue
            assert record.semantic_type.startswith("classification@headline:")
            fields = dict(record.fields)
            # IDs/fingerprints differ between independent runs. Compare the
            # actual native witnesses, including their metrics and provenance.
            fields.pop("best.evidence_digest")
            for key, value in tuple(fields.items()):
                if key.endswith("_record_ids"):
                    fields[key] = sorted(native[identifier] for identifier in value)
            signatures.append((summary_object_identity(portfolio), record.semantic_type,
                               json.dumps(fields, sort_keys=True)))
    return Counter(signatures)


def test_scoped_proposition_has_same_qualifiers_in_fresh_and_continuation_execution(graph):
    tail = SCOPED + "with lightcurve via fink\nconfirm by 1 via fink\n"
    fresh = execute_dsl(LOOKUP + tail, graph=graph, executor=Executor(), continue_from=None)
    executor = Executor()
    first = execute_dsl(LOOKUP, graph=graph, executor=executor, continue_from=None)
    snapshot = first.to_dict()
    continued = execute_dsl(tail, graph=graph, executor=executor, continue_from=first)
    assert identities(fresh.portfolios) == identities(continued.portfolios) == [IDS[0]]
    expected = lower_expression_predicate(QUALIFIED, frozenset({"classification"}))
    assert fresh.workflow.steps[-1].predicate == continued.workflow.steps[-1].predicate == expected
    assert scientific_records(fresh.portfolios) == scientific_records(continued.portfolios)
    assert first.to_dict() == snapshot
    assert continued.workflow.steps[:len(first.workflow.steps)] == first.workflow.steps
    # A later bare Confirm starts a new scope; no predicate is inherited from
    # the previous API call's surface or reconstructed from its executed IR.
    later = execute_dsl("confirm by 1 via fink\n", graph=graph, executor=executor, continue_from=continued)
    assert later.workflow.steps[-1].predicate is None
    assert later.workflow.steps[:len(continued.workflow.steps)] == continued.workflow.steps


def test_equivalent_qualified_general_and_scoped_conditions_bind_same_proposition(graph):
    general = LOOKUP + f"where {QUALIFIED}\nwith lightcurve via fink\nconfirm by 1 via fink\n"
    scoped = LOOKUP + SCOPED + "with lightcurve via fink\nconfirm by 1 via fink\n"
    results = [execute_dsl(source, graph=graph, executor=Executor(), continue_from=None)
               for source in (general, scoped)]
    assert results[0].workflow.steps[-1].predicate == results[1].workflow.steps[-1].predicate
    assert identities(results[0].portfolios) == identities(results[1].portfolios) == [IDS[0]]


@pytest.mark.parametrize("tail", [
    f"where {CONDITION}\n" + SCOPED + "confirm by 1 via fink\n",
    SCOPED + 'with classification via fink where best.class = "other"\nconfirm by 1 via fink\n',
])
def test_unrelated_conditions_cannot_silently_choose_or_drop_the_confirmation_question(graph, tail):
    executor = Executor()
    validation = validate_dsl(LOOKUP + tail, graph=graph, continue_from=None)
    assert validation.is_valid and not validation.is_runnable
    assert "multiple preceding conditions" in str(validation.lowering_error)
    with pytest.raises(SurfaceLoweringError, match="multiple preceding conditions"):
        execute_dsl(LOOKUP + tail, graph=graph, executor=executor, continue_from=None)
    assert executor.calls == []


def test_identical_explicit_conditions_do_not_create_an_ambiguous_question(graph):
    source = LOOKUP + SCOPED + SCOPED + "confirm by 1 via fink\n"
    result = execute_dsl(source, graph=graph, executor=Executor(), continue_from=None)
    assert identities(result.portfolios) == [IDS[0]]


def test_ambiguous_continuation_fails_without_changing_or_reexecuting_its_prefix(graph):
    executor = Executor()
    first = execute_dsl(LOOKUP, graph=graph, executor=executor, continue_from=None)
    snapshot, before = first.to_dict(), deepcopy(executor.calls)
    tail = SCOPED + 'with classification via fink where best.class = "other"\nconfirm by 1 via fink\n'
    validation = validate_dsl(tail, graph=graph, continue_from=first)
    assert validation.is_valid and not validation.is_runnable
    with pytest.raises(SurfaceLoweringError, match="multiple preceding conditions"):
        execute_dsl(tail, graph=graph, executor=executor, continue_from=first)
    assert first.to_dict() == snapshot
    assert executor.calls == before


def test_required_confirmation_failure_does_not_turn_into_abstention(graph):
    source = LOOKUP + f"where {CONDITION}\nwith lightcurve via fink\nconfirm by 1 via fink, lasair\n"
    with pytest.raises(WorkflowExecutionError, match="lasair evidence unavailable"):
        execute_dsl(source, graph=graph, executor=Executor(fail="lasair"), continue_from=None)


@pytest.mark.parametrize("boundary", [
    "filter summary.detection_count >= 1\n", "match on position inside 1arcsec\n",
    "confirm by 1 via fink\n",
])
def test_explicit_selection_match_and_prior_confirmation_end_attachment_scope(boundary):
    workflow = lower_surface(parse_surface_script(
        LOOKUP + f"where {CONDITION}\n" + boundary + "confirm by 1 via fink\n",
    )).workflow
    assert isinstance(workflow.steps[-1], ConfirmStep)
    assert workflow.steps[-1].predicate is None


def test_qualified_scoped_channel_is_not_erased_to_borrow_another_brokers_vote(graph):
    source = LOOKUP + 'with classification from sherlock via lasair where best.class = "SN"\nconfirm by 1 via fink\n'
    executor = Executor()
    assert not validate_dsl(source, graph=graph, continue_from=None).is_runnable
    with pytest.raises(SurfaceLoweringError):
        execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    assert executor.calls == []


def test_scoped_broker_list_retains_its_canonical_or_instead_of_inventing_a_quorum(graph):
    source = LOOKUP + 'with classification via fink, lasair where best.class = "SN"\nconfirm by 1 via fink, lasair\n'
    workflow = lower_surface(parse_surface_script(source)).workflow
    scoped_filter, confirm = workflow.steps[-2:]
    assert confirm.predicate == scoped_filter.predicate
    assert confirm.predicate.operator == "or"
    assert {p.left.channel for p in confirm.predicate.operands} == {"fink", "lasair"}
    # One voting endpoint cannot supply both channels. Preserve that capability
    # boundary rather than dropping qualifiers or treating the material list as votes.
    assert not validate_dsl(source, graph=graph, continue_from=None).is_runnable


def test_bare_confirmation_remains_existence_even_after_plain_material(graph):
    source = LOOKUP + "with lightcurve via fink\nconfirm by 2 via fink, lasair\n"
    result = execute_dsl(source, graph=graph, executor=Executor(), continue_from=None)
    assert result.workflow.steps[-1].predicate is None
    assert identities(result.portfolios) == list(IDS)
