"""Assertion ownership and unavailable evidence; synthetic, offline records only."""

from dataclasses import replace
from functools import lru_cache
from itertools import count

import pytest

from alertissimo.api import execute_dsl
from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId, InternalExecutionProvenance, InternalPortfolioId,
    InternalRecordId, InternalRecordSource, Portfolio, SemanticRecord,
)
from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraph, EndpointCapability, RequestConstraintCapability, build_capability_graph,
)
from alertissimo.data_layer.semantic_model import SemanticPathModel
from alertissimo.dsl import lower_surface, parse_surface_script
from alertissimo.orchestration.confirmation import confirm_step_portfolios
from alertissimo.orchestration.ir import ConfirmStep, Source
from alertissimo.orchestration.normalization import (
    ExecutionPortfolioResult, StepPortfolioResult,
    evaluate_portfolio_predicate, prune_portfolios,
    summary_object_identity,
)
from alertissimo.orchestration.planner import realize_predicate


OBJECT = "ZTF21abfmbix"
CLASS = "classification@lc_classifier:alerce"
SUMMARY = "summary@ztf:alerce"
LABEL = CLASS + '.best.class = "SN"'
SCORE = CLASS + ".best.probability >= 0.8"
COUNT = "summary.detection_count >= 5"


@lru_cache(maxsize=1)
def semantic_paths():
    return SemanticPathModel.from_ontology()


@lru_cache(maxsize=128)
def predicate(text):
    return lower_surface(parse_surface_script(
        f"object {OBJECT} from ztf via alerce\nfilter {text}\n"
    ), semantic_paths=semantic_paths()).workflow.steps[-1].predicate


def portfolio(*assertions, broker="alerce", name="candidate"):
    execution = InternalExecutionProvenance(
        internal_execution_id=InternalExecutionId(f"exec:{name}"),
        broker=broker, origin="ztf", endpoint="fixture",
    )
    rows = [(f"summary@ztf:{broker}", {
        "identity.object_id": OBJECT, "detection_count": 10,
    }), *assertions]
    return Portfolio(
        internal_portfolio_id=InternalPortfolioId(name),
        executions=(execution,),
        records=tuple(SemanticRecord(
            internal_record_id=InternalRecordId(f"{name}:{index}"),
            semantic_type=kind, fields=fields,
            internal_source=InternalRecordSource(
                internal_execution_id=execution.internal_execution_id,
                payload_key="fixture", payload_path="[]", payload_index=index,
            ),
        ) for index, (kind, fields) in enumerate(rows)),
    )


def assertion(label="SN", score=0.9, version="v1", kind=CLASS):
    return kind, {"best.class": label, "best.probability": score,
                  "provenance.producer.version": version}


@pytest.mark.parametrize("text", [
    f"{LABEL} and {SCORE} and {COUNT}",
    f"({LABEL} and {SCORE}) and {COUNT}",
    f"{LABEL} and ({SCORE} and {COUNT})",
    f"{COUNT} and {SCORE} and {LABEL}",
    f'({LABEL} or {CLASS}.best.class = "TDE") and {SCORE} and {COUNT}',
    f"not (not ({LABEL}) or not ({SCORE})) and {COUNT}",
])
def test_boolean_grouping_cannot_mix_class_and_score_between_versions(text):
    split = portfolio(assertion("SN", 0.2, "v1"), assertion("AGN", 0.99, "v2"))
    good = portfolio(assertion("SN", 0.9, "v1"), assertion("AGN", 0.99, "v2"), name="good")
    condition = predicate(text)
    assert not evaluate_portfolio_predicate(split, condition)
    assert evaluate_portfolio_predicate(good, condition)
    assert prune_portfolios((split, good), condition) == (good,)
    assert len(good.records) == 3  # Selection preserves the other assertion too.


def test_or_branches_and_other_brokers_keep_independent_witnesses():
    candidate = portfolio(assertion("SN", 0.2), assertion("AGN", 0.99, "v2"),
                          assertion("SN", 0.95, kind="classification@sherlock:lasair"))
    assert not evaluate_portfolio_predicate(candidate, predicate(f"{LABEL} and {SCORE} and {COUNT}"))
    other = 'classification@sherlock:lasair.best.class = "SN"'
    assert evaluate_portfolio_predicate(candidate, predicate(f"({LABEL} and {SCORE}) or {other}"))
    assert evaluate_portfolio_predicate(candidate, predicate(
        f"{LABEL} and {other} and classification@sherlock:lasair.best.probability >= 0.8"
    ))
    # An unavailable OR branch must not erase a separately established match.
    assert evaluate_portfolio_predicate(portfolio(), predicate(f"{LABEL} or {COUNT}"))


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), float("-inf"), "0.9", True, {}, []])
def test_unavailable_or_invalid_score_never_becomes_positive_under_negation(value):
    candidate = portfolio((CLASS, {"best.class": "SN", "best.probability": value}))
    for text in (SCORE, f"not ({SCORE})", f"not (not ({SCORE}))", f"not ({SCORE} and {COUNT})"):
        assert not evaluate_portfolio_predicate(candidate, predicate(text))


@pytest.mark.parametrize("assertions", [(), ((CLASS, {}),), ((CLASS, {"best.class": None}),)])
def test_absent_class_is_neither_sn_nor_non_sn(assertions):
    candidate = portfolio(*assertions)
    for text in (LABEL, f"not ({LABEL})", CLASS + '.best.class != "SN"'):
        assert not evaluate_portfolio_predicate(candidate, predicate(text))
    assert evaluate_portfolio_predicate(candidate, predicate(f"not ({LABEL}) or {COUNT}"))


def test_known_negative_and_unknown_boolean_branches_remain_distinct():
    candidate = portfolio(assertion("AGN", 0.2))
    assert evaluate_portfolio_predicate(candidate, predicate(f"not ({LABEL})"))
    assert evaluate_portfolio_predicate(candidate, predicate(CLASS + '.best.class != "SN"'))
    missing = CLASS + ".assessment.SN.probability >= 0.9"
    assert evaluate_portfolio_predicate(candidate, predicate(f"not ({LABEL}) or {missing}"))
    assert not evaluate_portfolio_predicate(candidate, predicate(f"not ({LABEL}) and {missing}"))
    assert not evaluate_portfolio_predicate(candidate, predicate(f"not ({LABEL} or {missing})"))


def test_explicit_absence_is_over_the_current_view_not_one_partial_record():
    family = f"exists {CLASS}"
    field = f"exists {CLASS}.best.class"
    empty = portfolio()
    partial = portfolio((CLASS, {"best.class": None}))
    populated = portfolio((CLASS, {}), assertion("SN", 0.9))
    assert evaluate_portfolio_predicate(empty, predicate(f"not {family}"))
    assert not evaluate_portfolio_predicate(empty, predicate(family))
    assert evaluate_portfolio_predicate(partial, predicate(family))
    assert evaluate_portfolio_predicate(partial, predicate(f"not {field}"))
    assert not evaluate_portfolio_predicate(populated, predicate(f"not {field}"))
    assert evaluate_portfolio_predicate(populated, predicate(f"not (not {field})"))
    assert evaluate_portfolio_predicate(empty, predicate(f"not ({family} or summary.detection_count < 0)"))


def test_positive_existence_still_belongs_to_the_same_assertion_as_its_score():
    split = portfolio((CLASS, {"best.class": "SN"}), (CLASS, {"best.probability": 0.99}))
    condition = predicate(f"exists {CLASS}.best.class and {SCORE} and {COUNT}")
    assert not evaluate_portfolio_predicate(split, condition)


def test_reference_comparisons_keep_both_fields_on_the_same_record():
    candidate = portfolio(
        (SUMMARY, {"time.first_mjd": 1, "time.last_mjd": 10}),
        (SUMMARY, {"time.first_mjd": 20, "time.last_mjd": 30}),
    )
    assert not evaluate_portfolio_predicate(candidate, predicate(
        "summary.time.first_mjd > summary.time.last_mjd"
    ))


def test_legacy_channel_comes_from_the_records_own_execution():
    candidate = portfolio(assertion(kind="classification@fink"), broker="fink")
    condition = predicate('classification@fink:fink.best.class = "SN"')
    assert evaluate_portfolio_predicate(candidate, condition)
    # Adding another broker to this Portfolio must not relabel existing records.
    other = replace(candidate.executions[0], internal_execution_id=InternalExecutionId("other"), broker="lasair")
    mixed = replace(candidate, executions=(*candidate.executions, other))
    assert not evaluate_portfolio_predicate(mixed, predicate('classification@fink:lasair.best.class = "SN"'))


def test_partial_native_filter_keeps_the_pushed_class_for_assertion_rechecking():
    endpoint = EndpointCapability(
        broker="alerce", origin="ztf", endpoint="fixture", path="/fixture", method="GET",
        operation_types=("object_search",), params=("class_name", "classifier"),
        server_filters=("class_name", "classifier"), projection_param=None,
        supports_projection=False, output_type="array",
    )
    constraints = tuple(RequestConstraintCapability(
        broker="alerce", origin="ztf", endpoint="fixture", parameter=parameter,
        semantic_path=path, operator="=",
    ) for parameter, path in (
        ("class_name", "classification.best.class"),
        ("classifier", "classification.provenance.producer.name"),
    ))
    graph = CapabilityGraph(
        endpoint_capabilities=(endpoint,), payload_capabilities=(), field_mapping_capabilities=(),
        transform_capabilities=(), semantic_record_capabilities=(), request_constraint_capabilities=constraints,
    )
    condition = predicate(f"{LABEL} and {SCORE} and {COUNT}")
    realization = realize_predicate(condition, endpoint=endpoint, graph=graph)
    assert realization.params == {"class_name": "SN", "classifier": "lc_classifier"}
    assert realization.pushdown == predicate(LABEL)
    assert realization.residual == condition
    split = portfolio(assertion("SN", 0.2), assertion("AGN", 0.99, "v2"))
    assert not evaluate_portfolio_predicate(split, realization.residual)
    assert evaluate_portfolio_predicate(portfolio(assertion()), realization.residual)


def test_proposition_quorum_does_not_count_a_missing_class_as_a_negative_vote():
    incoming = portfolio(name="incoming")
    known = portfolio(assertion("AGN", 0.9), name="known")
    unknown = portfolio(("classification@sherlock:lasair", {"best.probability": 0.99}),
                        broker="lasair", name="unknown")
    def view(index, *portfolios):
        return StepPortfolioResult(step_index=index, executions=tuple(
            ExecutionPortfolioResult(execution_id=p.executions[0].internal_execution_id.value, portfolios=(p,))
            for p in portfolios
        ))
    source, own = view(0, incoming), view(1, known, unknown)
    step = ConfirmStep(
        sources=[Source(broker="alerce", origin="ztf"), Source(broker="lasair", origin="ztf")],
        required_agreement=2, predicate=predicate('not (classification.best.class = "SN")'),
    )
    result = confirm_step_portfolios(step, source, own, step_index=1)
    assert result.portfolios == ()
    assert result.executions == own.executions
    # One established non-SN assertion is still a valid one-broker quorum.
    passed = confirm_step_portfolios(step.model_copy(update={"required_agreement": 1}), source, own, step_index=1)
    assert len(passed.portfolios) == 1


def test_proposition_quorum_cannot_mix_a_class_with_another_versions_score():
    incoming = portfolio(name="incoming")
    split = portfolio(assertion("SN", 0.2), assertion("AGN", 0.99, "v2"), name="split")
    source = StepPortfolioResult(step_index=0, executions=(), materialized_portfolios=(incoming,))
    own = StepPortfolioResult(step_index=1, executions=(ExecutionPortfolioResult(
        execution_id=split.executions[0].internal_execution_id.value, portfolios=(split,),
    ),))
    step = ConfirmStep(sources=[Source(broker="alerce", origin="ztf")], required_agreement=1,
                       predicate=predicate(f"{LABEL} and {SCORE} and {COUNT}"))
    result = confirm_step_portfolios(step, source, own, step_index=1)
    assert result.portfolios == ()
    assert result.executions == own.executions


class WorkflowExecutor:
    """Two candidates; one has split class/score evidence, the other one witness."""
    ids = ("ZTF20aaaaaaa", "ZTF20bbbbbbb")

    def __init__(self):
        self.calls = []
        self.execution_ids = count()

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        params = dict(params or {})
        self.calls.append((broker, endpoint, params))
        if (broker, endpoint) == ("alerce", "query_object"):
            payload = {"oid": params["oid"], "meanra": 120.0, "meandec": -6.0, "ndet": 2,
                       "firstmjd": 59000.0, "lastmjd": 59002.0}
        else:
            assert (broker, endpoint) == ("fink", "objects")
            payload = [
                {"i:objectId": oid, "i:candid": 1000 + index * 10 + point, "i:jd": 2459000.5 + point,
                 "i:fid": 1, "i:magpsf": 19.0, "i:sigmapsf": 0.1, "i:ndethist": 2,
                 "i:ra": 120.0, "i:dec": -6.0,
                 "v:classification": "SN candidate" if point == 0 else "AGN",
                 "d:snn_sn_vs_all": (0.2 if oid == self.ids[0] else 0.9) if point == 0 else 0.99}
                for index, oid in enumerate(params["objectId"].split(",")) for point in range(2)
            ]
        return ExecutionResult(payload=payload, execution_provenance=InternalExecutionProvenance(
            internal_execution_id=InternalExecutionId(f"workflow:{next(self.execution_ids)}"),
            broker=broker, origin=origin, endpoint=endpoint, params=params,
        ))


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def test_fresh_and_continuation_select_the_same_assertion_without_losing_measurements(graph):
    base = f"objects {','.join(WorkflowExecutor.ids)} from ztf via alerce\n"
    scoped = ('best.class = "SN candidate" and assessment.sn_vs_all.probability >= 0.8 '
              'and summary.detection_count >= 1')
    fresh = execute_dsl(base + "with classification via fink where " + scoped + "\n",
                        graph=graph, executor=WorkflowExecutor(), continue_from=None)
    executor = WorkflowExecutor()
    first = execute_dsl(base + "with classification via fink\n",
                        graph=graph, executor=executor, continue_from=None)
    old_calls, snapshot = list(executor.calls), first.to_dict()
    second = execute_dsl(
        'filter classification@fink:fink.best.class = "SN candidate" and '
        'classification@fink:fink.assessment.sn_vs_all.probability >= 0.8 '
        'and summary.detection_count >= 1\n',
        graph=graph, executor=executor, continue_from=first,
    )
    expected = {("ztf", WorkflowExecutor.ids[1])}
    assert {summary_object_identity(p) for p in fresh.portfolios} == expected
    assert {summary_object_identity(p) for p in second.portfolios} == expected
    assert first.to_dict() == snapshot
    assert second.workflow.steps[:len(first.workflow.steps)] == first.workflow.steps
    assert executor.calls == old_calls
    for result in (fresh, second):
        assert sum(r.semantic_type == "measurement@ztf:fink" for p in result.portfolios for r in p.records) == 2
        # Both the qualifying row and the other row remain available to inspect.
        assert {r.get("best.class") for p in result.portfolios for r in p.records
                if r.semantic_type == "classification@fink"} == {"SN candidate", "AGN"}
