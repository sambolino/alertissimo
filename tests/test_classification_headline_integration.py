"""Stored headline boundaries and public normalized confirmation (offline only)."""
from dataclasses import replace
from itertools import count
import json

import pytest

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId, InternalExecutionProvenance, InternalPortfolioId,
    InternalRecordId, InternalRecordSource, Portfolio, SemanticRecord,
)
from alertissimo.data_layer.runtime import classification_headline as policy
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.data_layer.runtime.serialization import portfolio_to_dict, portfolio_to_json
from alertissimo.data_layer.presentation.portfolio_classification import classification_rows
from alertissimo.dsl.predicate_lowering import lower_expression_predicate
from alertissimo.orchestration.confirmation.confirm import confirm_step_portfolios
from alertissimo.orchestration.ir import ConfirmStep, Source
from alertissimo.orchestration.normalization import (
    ExecutionPortfolioResult, StepPortfolioResult, consolidate_portfolios,
    evaluate_portfolio_predicate, summary_object_identity,
)


def evidence(broker, producer, fields, *, execution="one", survey="ztf"):
    eid = InternalExecutionId(f"execution:{broker}:{execution}")
    source = InternalRecordSource(eid, "fixture", ".")
    return Portfolio(InternalPortfolioId(f"portfolio:{eid.value}"), (
        SemanticRecord(InternalRecordId(f"summary:{eid.value}"), f"summary@{survey}:{broker}",
                       {"identity.object_id": "ZTF20aaaaaaa"}, source),
        SemanticRecord(InternalRecordId(f"class:{eid.value}"), f"classification@{producer}:{broker}", fields, source),
    ), executions=(InternalExecutionProvenance(eid, broker, survey, "fixture"),))


def headline(p, broker="alerce"):
    return next(r for r in p.records if r.semantic_type == f"classification@headline:{broker}")


def predicate(text='classification.best.coarse_class = "supernova"'):
    return lower_expression_predicate(text, frozenset({"classification"}))


def test_stored_interpretation_is_pinned_and_presentation_never_loads_policy(monkeypatch):
    raw = evidence("alerce", "lc_classifier", {"best.class": "SNIa", "best.probability": 0.01})
    saved = policy.materialize_headlines(raw)
    native_ids = {r.internal_record_id for r in raw.records}
    assert [r for r in saved.records if r.internal_record_id in native_ids] == list(raw.records)
    assert headline(saved).get("best.coarse_class") == "supernova"
    before = portfolio_to_dict(saved)
    def forbidden(*args, **kwargs):
        raise AssertionError("stored results must not load the current policy")
    monkeypatch.setattr(policy, "load_policy", forbidden)
    assert policy.materialize_headlines(saved) is saved
    serialized = json.loads(portfolio_to_json(saved))
    assert classification_rows(saved) == classification_rows(serialized)
    assert portfolio_to_dict(saved) == before
    assert not any(r.get("headline") for r in classification_rows(raw))


def test_new_material_replaces_only_new_views_headline_and_retains_alternatives():
    first = policy.materialize_headlines(evidence("alerce", "stamp_classifier", {"best.class": "AGN"}))
    before = portfolio_to_dict(first)
    lc = evidence("alerce", "lc_classifier", {"best.class": "SNIa"}, execution="lc")
    merged, = consolidate_portfolios((first, lc))
    second = policy.materialize_headlines(merged)
    assert headline(first).get("best.coarse_class") == "agn"
    assert headline(second).get("best.coarse_class") == "supernova"
    assert len([r for r in second.records if policy.is_headline_record(r)]) == 1
    assert {r.get("best.class") for r in second.records if not policy.is_headline_record(r)} >= {"AGN", "SNIa"}
    assert portfolio_to_dict(first) == before


@pytest.mark.parametrize("label,status", [("Unknown", "sentinel"), ("(TNS) Galaxy", "recognized_no_proposition")])
def test_abstention_cannot_become_positive_under_not(label, status):
    p = policy.materialize_headlines(evidence("fink", "fink", {"best.class": label}))
    assert headline(p, "fink").get("best.status") == status
    assert not evaluate_portfolio_predicate(p, predicate())
    assert not evaluate_portfolio_predicate(p, predicate('not (classification.best.coarse_class = "supernova")'))


def test_unknown_vocabulary_is_visible_and_cannot_silently_filter_away():
    p = policy.materialize_headlines(evidence("alerce", "lc_classifier", {"best.class": "new-label"}))
    assert headline(p).get("best.error_code") == "unmapped_label"
    assert any(r["error"] == "unmapped_label" for r in classification_rows(p))
    with pytest.raises(policy.HeadlinePolicyError, match="unmapped_label"):
        evaluate_portfolio_predicate(p, predicate())
    assert evaluate_portfolio_predicate(p, predicate('classification.best.status = "error"'))


def test_native_predicates_do_not_match_derived_metadata_or_mix_assertions():
    p = policy.materialize_headlines(evidence("alerce", "lc_classifier", {"best.class": "SNIa", "best.probability": 0.7}))
    assert evaluate_portfolio_predicate(p, predicate('classification.best.class = "SNIa"'))
    assert not evaluate_portfolio_predicate(p, predicate('classification.best.coarse_class = "supernova" and classification.best.probability > 0.5'))
    assert evaluate_portfolio_predicate(p, predicate('classification.best.coarse_class = "supernova" and classification.best.native_probability > 0.5'))


def test_confirm_combines_own_broker_calls_before_selecting_and_deduplicates_votes():
    source = StepPortfolioResult(0, (), (evidence("fink", "fink", {"best.class": "SN candidate"}),))
    # High-probability stamp cannot vote over the preferred LC result.
    stamp = evidence("alerce", "stamp_classifier", {"best.class": "SN", "best.probability": 0.99})
    lc = evidence("alerce", "lc_classifier", {"best.class": "AGN", "best.probability": 0.01}, execution="lc")
    def own(*portfolios):
        return StepPortfolioResult(1, tuple(ExecutionPortfolioResult(p.executions[0].internal_execution_id.value, (p,)) for p in portfolios))
    step = ConfirmStep(sources=[Source(broker="alerce", origin="ztf")], predicate=predicate())
    assert confirm_step_portfolios(step, source, own(stamp, lc), step_index=1).portfolios == ()
    step = ConfirmStep(required_agreement=2, predicate=predicate())
    assert confirm_step_portfolios(step, source, own(stamp, stamp), step_index=1).portfolios == ()


@pytest.mark.parametrize("survey,status", [("ztf", "input_scope_unresolved"), ("lsst", "headline_unresolved")])
def test_antares_mixed_locus_never_invents_classifier_survey(survey, status):
    p = policy.materialize_headlines(evidence("antares", "superphot_plus", {"best.class": "SN Ia"}, survey=survey))
    assert headline(p, "antares").get("best.status") == status
    assert not evaluate_portfolio_predicate(p, predicate())


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


class Executor:
    """Controlled broker-native payloads; differing candidate outcomes are deliberate."""
    def __init__(self):
        self.calls, self.sequence = [], count()
    def execute(self, broker, origin, endpoint, params=None, headers=None):
        params = dict(params or {})
        self.calls.append((broker, endpoint, params))
        if broker == "alerce" and endpoint == "query_object":
            payload = {"oid": params["oid"], "meanra": 10., "meandec": 20., "ndet": 2}
        elif broker == "alerce" and endpoint == "query_probabilities":
            payload = [{"classifier_name": "lc_classifier", "classifier_version": v,
                        "class_name": label, "probability": 0.9, "ranking": 1}
                       for v, label in (("old", "AGN"), ("new", "SNIa"))]
        elif broker == "alerce" and endpoint == "query_objects":
            label = "SNIa" if params["classifier"] == "lc_classifier" else "AGN"
            payload = {"items": [{"oid": params["oid"], "classifier": params["classifier"],
                                  "class": label, "probability": 0.1}], "total": 1}
        elif broker == "fink":
            payload = [{"i:objectId": oid, "i:candid": 1, "i:jd": 2459000.5,
                        "i:ra": 10., "i:dec": 20., "v:classification": "SN candidate"}
                       for oid in params["objectId"].split(",")]
        else:
            assert broker == "lasair"
            payload = [{"objectId": oid, "objectData": {"ramean": 10., "decmean": 20.},
                        "sherlock": {"classification": "SN", "classificationReliability": 3}, "candidates": []}
                       for oid in params["objectIds"].split(",")]
        return ExecutionResult(payload=payload, execution_provenance=InternalExecutionProvenance(
            InternalExecutionId(f"headline-integration:{next(self.sequence)}"), broker, origin, endpoint, params))


def test_public_confirm_uses_composed_alerce_recipe_and_broker_local_headlines(graph, monkeypatch):
    source = ('objects ZTF20aaaaaaa from ztf via alerce\n'
              'where classification.best.coarse_class = "supernova"\n'
              'confirm by 3 via alerce, fink, lasair\n')
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    executor = Executor()
    result = execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    assert [summary_object_identity(p) for p in result.portfolios] == [("ztf", "ZTF20aaaaaaa")]
    assert len([c for c in executor.calls if c[:2] == ("alerce", "query_objects")]) == 2
    p, = result.portfolios
    assert {r.get("best.broker") for r in p.records if policy.is_headline_record(r)} == {"alerce", "fink", "lasair"}
    assert headline(p, "lasair").get("best.native_score") == 3
    assert headline(p, "lasair").get("best.native_probability") is None
    before, call_count = result.to_dict(), len(executor.calls)
    def changed_policy(*args, **kwargs):
        raise AssertionError("continuation must keep the prior interpretation")
    monkeypatch.setattr(policy, "load_policy", changed_policy)
    continued = execute_dsl('filter classification.best.coarse_class = "supernova"',
                            graph=graph, executor=executor, continue_from=result)
    assert len(continued.portfolios) == 1
    assert result.to_dict() == before and len(executor.calls) == call_count
    # Every native call for this survivor remains intact, including alternative
    # labels that would fail if evaluated as independent headline candidates.
    assert continued.result.steps[-1].executions == result.result.steps[-1].executions
    assert continued.portfolios == result.portfolios
    # The final normalizer and staged executor must use the same material rule.
    from alertissimo.orchestration.normalization.normalize import _filter_candidate_view
    normalized = _filter_candidate_view(continued.workflow.steps[-1], continued.run.steps[-1],
                                        list(result.result.steps))
    assert normalized.executions == result.result.steps[-1].executions
    assert normalized.portfolios == result.portfolios


def test_unbounded_normalized_discovery_is_not_silently_broadened(graph):
    result = validate_dsl('objects from ztf via alerce\nwhere classification.best.coarse_class = "supernova"',
                          graph=graph, continue_from=None)
    assert not result.is_runnable


def test_cone_normalized_selection_precedes_latest(graph):
    result = validate_dsl('objects from ztf via alerce\ninside (10, 20, 5arcsec)\n'
                          'where classification.best.coarse_class = "supernova"\nlatest 1',
                          graph=graph, continue_from=None)
    assert result.is_runnable, result.lowering_error
    # Validate the actual lowered operations without fetching any provider data.
    from alertissimo.dsl import lower_surface, parse_surface_script
    workflow = lower_surface(parse_surface_script(
        'objects from ztf via alerce\ninside (10, 20, 5arcsec)\n'
        'where classification.best.coarse_class = "supernova"\nlatest 1'), graph=graph).workflow
    assert [step.op for step in workflow.steps] == ["cone_search", "get_classification", "filter"]
    assert workflow.steps[0].selection.after_step == 2


def test_bounded_discovery_filters_coarse_class_before_global_latest(graph):
    class ConeExecutor(Executor):
        def execute(self, broker, origin, endpoint, params=None, headers=None):
            params = dict(params or {})
            if endpoint == "query_objects" and "ra" in params:
                self.calls.append((broker, endpoint, params))
                payload = {"items": [
                    {"oid": oid, "meanra": 10., "meandec": 20., "ndet": 2,
                     "firstmjd": 59000., "lastmjd": last}
                    for oid, last in (("ZTF20aaaaaaa", 59001.), ("ZTF20bbbbbbb", 59002.))
                ], "total": 2}
                return ExecutionResult(payload=payload, execution_provenance=InternalExecutionProvenance(
                    InternalExecutionId(f"headline-integration:{next(self.sequence)}"), broker, origin, endpoint, params))
            result = super().execute(broker, origin, endpoint, params, headers)
            if endpoint == "query_objects" and params.get("oid") == "ZTF20bbbbbbb":
                result.payload["items"][0]["class"] = "AGN"
            return result
    executor = ConeExecutor()
    result = execute_dsl('objects from ztf via alerce\ninside (10, 20, 5arcsec)\n'
                         'where classification.best.coarse_class = "supernova"\nlatest 1',
                         graph=graph, executor=executor, continue_from=None)
    assert [summary_object_identity(p) for p in result.portfolios] == [("ztf", "ZTF20aaaaaaa")]
    assert {params["oid"] for _, endpoint, params in executor.calls if endpoint == "query_probabilities"} == {
        "ZTF20aaaaaaa", "ZTF20bbbbbbb",
    }
