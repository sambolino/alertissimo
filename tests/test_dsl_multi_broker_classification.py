"""Broker-list syntax reuses existing retrieval Steps; no provider IO."""

from functools import lru_cache
from itertools import count

import pytest

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId, InternalExecutionProvenance, InternalPortfolioId,
    InternalRecordId, Portfolio, SemanticRecord,
)
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.data_layer.semantic_model import SemanticPathModel
from alertissimo.dsl import (
    DSLParseError, SurfaceLoweringError, SurfaceScript, compile_surface_fragment,
    lower_surface, parse_surface_fragment, parse_surface_script, validate_surface_capabilities,
)
from alertissimo.orchestration.ir import WorkflowIR, iter_semantic_references
from alertissimo.orchestration.normalization import evaluate_portfolio_predicate, summary_object_identity


A, B = "ZTF21abfmbix", "ZTF20acpwljl"
LOOKUP = f"objects {A}, {B} from ztf via alerce\n"
MULTI = "with classification via alerce, fink\n"


@lru_cache(maxsize=1)
def semantic_paths():
    return SemanticPathModel.from_ontology()


def lower(source):
    return lower_surface(parse_surface_script(source), semantic_paths=semantic_paths()).workflow


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def test_list_preserves_one_authored_clause_and_single_broker_compatibility():
    surface = parse_surface_script(LOOKUP + "with classification via ALeRCE, Fink\n")
    assert len(surface.clauses) == 1
    assert surface.clauses[0].brokers == ("alerce", "fink")
    assert surface.clauses[0].via is None
    assert SurfaceScript.model_validate_json(surface.model_dump_json()) == surface
    single = parse_surface_script(LOOKUP + "with classification via fink\n").clauses[0]
    assert single.via == "fink" and single.brokers == ()
    assert single.broker_requirements() == (single,)


@pytest.mark.parametrize("source", [
    LOOKUP + "with classification via fink, FINK\n",
    LOOKUP + "with classification via alerce,\n",
    LOOKUP + "with classification via ,fink\n",
    LOOKUP + "with lightcurve via alerce, fink\n",
    "objects from ztf via alerce, fink\n",
])
def test_invalid_or_out_of_scope_lists_fail_at_parsing(source):
    with pytest.raises(DSLParseError):
        parse_surface_script(source)


def test_list_and_explicit_requirements_emit_identical_existing_ir():
    listed = lower(LOOKUP + MULTI)
    explicit = lower(LOOKUP + "with classification via alerce\nwith classification via fink\n")
    assert listed == explicit
    assert [step.op for step in listed.steps] == ["lookup", "get_classification", "get_classification"]
    assert [step.sources[0].broker for step in listed.steps[1:]] == ["alerce", "fink"]
    assert WorkflowIR.model_validate_json(listed.model_dump_json()) == listed
    assert lower(LOOKUP + MULTI + "with classification via fink\n" + MULTI) == listed


def test_capability_reports_keep_original_clause_index_and_each_broker(graph):
    surface = parse_surface_script(LOOKUP + MULTI + "with classification via fink\n")
    report = validate_surface_capabilities(surface, graph=graph, semantic_paths=semantic_paths())
    checks = [check for check in report.checks if check.subject == "requirement"]
    assert report.is_supported
    assert {(check.broker, check.channel, check.clause_index) for check in checks} == {
        ("alerce", "alerce", 0), ("fink", "fink", 0),
    }
    assert all(check.evidence for check in checks)


def test_scoped_condition_requires_one_brokers_whole_predicate():
    workflow = lower(LOOKUP +
        'with classification via alerce, fink where best.class = "SN" and best.probability >= 0.8\n')
    condition = workflow.steps[-1].predicate
    assert condition.operator == "or"
    assert [{ref.channel for ref in iter_semantic_references(part)} for part in condition.operands] == [
        {"alerce"}, {"fink"},
    ]
    def candidate(probability):
        return Portfolio(internal_portfolio_id=InternalPortfolioId("candidate"), records=(
            SemanticRecord(internal_record_id=InternalRecordId("one"), semantic_type="classification@model:alerce",
                           fields={"best.class": "SN", "best.probability": probability}),
            SemanticRecord(internal_record_id=InternalRecordId("two"), semantic_type="classification@model:fink",
                           fields={"best.class": "AGN", "best.probability": 0.99}),
        ))
    assert not evaluate_portfolio_predicate(candidate(0.2), condition)
    assert evaluate_portfolio_predicate(candidate(0.9), condition)


class Executor:
    def __init__(self, *, empty_fink=False):
        self.calls, self.ids = [], count()
        self.empty_fink = empty_fink

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        params = dict(params or {})
        self.calls.append((broker, endpoint, params))
        assert origin == "ztf"
        if (broker, endpoint) == ("alerce", "query_object"):
            payload = {"oid": params["oid"], "meanra": 120.0, "meandec": -6.0, "ndet": 2,
                       "firstmjd": 59000.0, "lastmjd": 59002.0}
        elif (broker, endpoint) == ("alerce", "query_probabilities"):
            payload = [{"class_name": "SNIa", "classifier_name": "lc_classifier", "classifier_version": "v1",
                        "probability": 0.9 if params["oid"] == A else 0.2, "ranking": 1}]
        else:
            assert (broker, endpoint) == ("fink", "objects")
            payload = [] if self.empty_fink else [
                {"i:objectId": oid, "i:candid": 1000 + index * 10 + point, "i:jd": 2459000.5 + point,
                 "i:fid": 1, "i:magpsf": 19.0, "i:sigmapsf": 0.1, "i:ndethist": 2,
                 "i:ra": 120.0, "i:dec": -6.0,
                 "v:classification": "SN candidate" if oid == B else "AGN",
                 "d:snn_sn_vs_all": 0.9 if oid == B else 0.2}
                for index, oid in enumerate(params["objectId"].split(",")) for point in range(2)
            ]
        return ExecutionResult(payload=payload, execution_provenance=InternalExecutionProvenance(
            internal_execution_id=InternalExecutionId(f"multi:{next(self.ids)}"),
            broker=broker, origin=origin, endpoint=endpoint, params=params,
        ))


def identities(result):
    return {summary_object_identity(portfolio) for portfolio in result.portfolios}


@pytest.mark.parametrize("brokers", ["alerce, fink", "fink, alerce"])
@pytest.mark.parametrize("empty_fink", [False, True])
def test_public_retrieval_retains_candidates_and_attributable_assertions(graph, brokers, empty_fink):
    executor = Executor(empty_fink=empty_fink)
    source = LOOKUP + f"with classification via {brokers}\n"
    assert validate_dsl(source, graph=graph, continue_from=None).is_runnable
    assert executor.calls == []
    result = execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    assert identities(result) == {("ztf", A), ("ztf", B)}
    assert [name for _, name, _ in executor.calls].count("query_probabilities") == 2
    assert [name for _, name, _ in executor.calls].count("objects") == 1
    for portfolio in result.portfolios:
        classes = [r for r in portfolio.records if r.semantic_type.startswith("classification@")]
        expected = {"alerce"} if empty_fink else {"alerce", "fink"}
        assert {portfolio.execution(r.internal_source.internal_execution_id).broker for r in classes} == expected


def test_scoped_selection_and_continuation_reuse_the_same_material(graph):
    scoped = 'best.class = "SN candidate" and assessment.sn_vs_all.probability >= 0.8'
    fresh = execute_dsl(LOOKUP + MULTI.rstrip() + " where " + scoped + "\n",
                        graph=graph, executor=Executor(), continue_from=None)
    executor = Executor()
    first = execute_dsl(LOOKUP + "with classification via alerce\n",
                        graph=graph, executor=executor, continue_from=None)
    snapshot, before_calls = first.to_dict(), len(executor.calls)
    clause = MULTI.rstrip() + " where " + scoped + "\n"
    assert validate_dsl(clause, graph=graph, continue_from=first).is_runnable
    second = execute_dsl(clause, graph=graph, executor=executor, continue_from=first)
    assert identities(second) == identities(fresh) == {("ztf", B)}
    assert len(executor.calls) == before_calls + 1
    assert executor.calls[-1][1] == "objects"
    assert second.workflow.steps[:len(first.workflow.steps)] == first.workflow.steps
    assert first.to_dict() == snapshot
    assert sum(r.semantic_type == "measurement@ztf:fink" for p in second.portfolios for r in p.records) == 2
    assert compile_surface_fragment(parse_surface_fragment(MULTI), second.workflow, graph=graph).workflow.steps == second.workflow.steps


@pytest.mark.parametrize("clause", [
    "with classification via alerce, no_such_broker\n",
    "with classification from lc_classifier via alerce, fink\n",
])
def test_unavailable_list_member_is_not_silently_dropped(graph, clause):
    source = LOOKUP + clause
    assert not validate_dsl(source, graph=graph, continue_from=None).is_runnable
    executor = Executor()
    with pytest.raises(SurfaceLoweringError) as caught:
        execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    assert caught.value.clause_index == 0
    assert executor.calls == []


def test_discovery_still_defers_conditions_requiring_later_broker_material(graph):
    source = ('objects from ztf via alerce\ninside (120, -6, 5arcsec)\n'
              'with classification via alerce, fink where best.class = "SN candidate"\n')
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_valid and not validation.is_runnable
    assert "discovery residual requires material unavailable" in str(validation.lowering_error)
