"""Counterexamples for opt-in native headline selection; no network requests."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from alertissimo.data_layer.representations import (
    InternalExecutionId, InternalExecutionProvenance, InternalPortfolioId,
    InternalRecordId, InternalRecordSource, Portfolio, SemanticRecord,
)
from alertissimo.data_layer.runtime.classification_headline import (
    HeadlinePolicyError, derive_headline_fields, load_policy, validate_policy,
)
from alertissimo.data_layer.runtime.record_builder import build_portfolios_from_execution
from alertissimo.data_layer.execution import ExecutionResult


ROOT = Path(__file__).parents[1]


def portfolio(broker="alerce", origin="ztf", rows=(), times=None):
    execution_id = InternalExecutionId("execution:test")
    records = [SemanticRecord(InternalRecordId("record:summary"), f"summary@{origin}:{broker}",
                              {"identity.object_id": "object-1"})]
    for index, (producer, fields) in enumerate(rows):
        source = InternalRecordSource(execution_id, "fixture", "[]", index)
        records.append(SemanticRecord(InternalRecordId(f"record:{index}"),
                                      f"classification@{producer}:{broker}", fields, source))
        if times is not None and times[index] is not None:
            records.append(SemanticRecord(InternalRecordId(f"measurement:{index}"),
                                          f"measurement@{origin}:{broker}",
                                          {"time.mjd": times[index]}, source))
    return Portfolio(InternalPortfolioId("portfolio:test"), tuple(records), executions=(
        InternalExecutionProvenance(execution_id, broker, origin, "fixture"),
    ))


def ranked(label, version="test-version", probability=0.5, rank=1):
    return {"assessment.result.class": label, "assessment.result.rank": rank,
            "assessment.result.probability": probability, "provenance.producer.version": version}


@pytest.mark.parametrize("broker", ["alerce", "fink", "lasair", "antares"])
@pytest.mark.parametrize("origin", ["ztf", "lsst"])
def test_all_eight_packaged_policies_validate(broker, origin):
    validate_policy(load_policy(broker, origin))


def test_lc_precedence_is_not_probability_maximization_and_does_not_mutate_inputs():
    p = portfolio(rows=[("lc_classifier", ranked("SNIa", probability=0.01)),
                        ("stamp_classifier", ranked("AGN", probability=0.99))])
    original = tuple(dict(r.fields) for r in p.records)
    result = derive_headline_fields(p, broker="alerce", origin="ztf")
    assert result["best.coarse_class"] == "supernova"
    assert result["best.native_class"] == "SNIa"
    assert result["best.subtype"] == "Ia"
    assert result["best.native_probability"] == 0.01
    assert result["best.source_method"] == "lc_classifier"
    assert result["best.candidate_status"] == "candidate"
    assert result["best.selected_record_ids"] == ("record:0",)
    assert result["best.input_record_ids"] == ("record:0", "record:1")
    assert tuple(dict(r.fields) for r in p.records) == original


def test_stamp_fallback_only_when_lc_has_no_selected_output():
    p = portfolio(rows=[("lc_classifier", ranked("SNIa", rank=2)),
                        ("stamp_classifier", ranked("AGN"))])
    result = derive_headline_fields(p, broker="alerce", origin="ztf")
    assert result["best.source_method"] == "stamp_classifier"
    assert result["best.coarse_class"] == "agn"


def test_broker_selected_summary_resolves_historical_probability_versions():
    p = portfolio(rows=[("lc_classifier", ranked("SNIa", version="old")),
                        ("lc_classifier", ranked("SNII", version="new")),
                        ("lc_classifier", {"best.class": "SNIbc", "best.probability": 0.525456})])
    result = derive_headline_fields(p, broker="alerce", origin="ztf")
    assert result["best.native_class"] == "SNIbc"
    assert result["best.source_version"] is None
    assert result["best.selected_record_ids"] == ("record:2",)


@pytest.mark.parametrize("second_label", ["SNIa", "SNII"])
def test_multiple_versions_abstain_even_when_labels_agree(second_label):
    p = portfolio(rows=[("lc_classifier", ranked("SNIa", version="1.0")),
                        ("lc_classifier", ranked(second_label, version="99.0")),
                        ("stamp_classifier", ranked("SN"))])
    result = derive_headline_fields(p, broker="alerce", origin="ztf")
    assert result["best.status"] == "conflict"
    assert "best.coarse_class" not in result
    assert result["best.source_method"] == "lc_classifier"


def test_same_version_rank_one_tie_is_not_broken_by_probability_or_order():
    rows = [("lc_classifier", ranked("SNIa", probability=0.9)),
            ("lc_classifier", ranked("AGN", probability=0.1))]
    for ordered in (rows, list(reversed(rows))):
        result = derive_headline_fields(portfolio(rows=ordered), broker="alerce", origin="ztf")
        assert result["best.status"] == "conflict"


def test_new_label_fails_explicitly_without_fallback_or_native_data_loss():
    p = portfolio(rows=[("lc_classifier", ranked("UnreviewedClass")),
                        ("stamp_classifier", ranked("SN"))])
    result = derive_headline_fields(p, broker="alerce", origin="ztf")
    assert result["best.status"] == "error"
    assert result["best.error_code"] == "unmapped_label"
    assert result["best.native_class"] == "UnreviewedClass"
    assert "best.coarse_class" not in result


def test_duplicate_witnesses_do_not_choose_a_metric():
    p = portfolio(rows=[("stamp_classifier", ranked("SN", probability=0.2)),
                        ("stamp_classifier", ranked("SN", probability=0.8))])
    result = derive_headline_fields(p, broker="alerce", origin="ztf")
    assert result["best.coarse_class"] == "supernova"
    assert "best.native_probability" not in result
    assert result["best.selected_record_ids"] == ("record:0", "record:1")


@pytest.mark.parametrize("version", [202, "2.0.2"])
def test_lsst_pinned_method_and_explicit_native_version_identifiers(version):
    p = portfolio(origin="lsst", rows=[
        ("stamp_classifier_rubin_beta", ranked("AGN", version=201, probability=0.99)),
        ("stamp_classifier_rubin_beta_20260421", ranked("SN", version=version, probability=0.1)),
    ])
    result = derive_headline_fields(p, broker="alerce", origin="lsst")
    assert result["best.coarse_class"] == "supernova"
    assert result["best.source_version"] == version


@pytest.mark.parametrize("version", [None, "202", 203, "2.0.3"])
def test_unreviewed_lsst_versions_abstain(version):
    p = portfolio(origin="lsst", rows=[("stamp_classifier_rubin_beta_20260421", ranked("SN", version=version))])
    result = derive_headline_fields(p, broker="alerce", origin="lsst")
    assert result["best.status"] == "unsupported_version"
    assert "best.coarse_class" not in result


def test_new_classifier_never_displaces_pinned_method():
    p = portfolio(origin="lsst", rows=[("stamp_classifier_rubin_beta_20990101", ranked("SN", version="100"))])
    assert derive_headline_fields(p, broker="alerce", origin="lsst")["best.status"] == "missing"


def test_fink_latest_uses_exact_row_linked_observation_not_score_or_array_order():
    p = portfolio("fink", rows=[("fink", {"best.class": "SN candidate"}),
                                 ("fink", {"best.class": "Microlensing candidate"})], times=[60002, 60001])
    result = derive_headline_fields(p, broker="fink", origin="ztf")
    assert result["best.coarse_class"] == "supernova"
    assert result["best.observation_mjd"] == 60002


def test_fink_missing_observation_order_and_ties_abstain():
    rows = [("fink", {"best.class": "SN candidate"}), ("fink", {"best.class": "Microlensing candidate"})]
    for times, status in [([60002, None], "observation_order_unresolved"), ([60002, 60002], "conflict")]:
        result = derive_headline_fields(portfolio("fink", rows=rows, times=times), broker="fink", origin="ztf")
        assert result["best.status"] == status
        assert "best.coarse_class" not in result


def test_fink_full_catalogue_and_unknown_sentinel_are_accounted_separately():
    policy = load_policy("fink", "ztf")
    # 369 published labels, of which Ambiguous is a sentinel; Unknown is additional.
    assert len(policy["vocabulary"]) == 368
    assert len(policy["sentinels"]) == 2
    for label in ["Unknown", "Ambiguous"]:
        result = derive_headline_fields(portfolio("fink", rows=[("fink", {"best.class": label})]), broker="fink", origin="ztf")
        assert result["best.status"] == "sentinel"
    label = "(TNS) SN Ia"
    assert any(v["label"] == label for v in policy["vocabulary"])
    result = derive_headline_fields(portfolio("fink", rows=[("fink", {"best.class": label})]), broker="fink", origin="ztf")
    assert result["best.scope"] == "catalogue_association"
    assert "best.coarse_class" not in result


@pytest.mark.parametrize("code,expected", [(11,"supernova"), (12,"fast_transient"), (13,"long_transient"), (21,"periodic"), (22,"nonperiodic")])
def test_fink_lsst_codes_have_finite_explicit_meanings(code, expected):
    p = portfolio("fink", "lsst", [("fink", {"best.class": code, "assessment.crossmatch.class": "AGN"})])
    assert derive_headline_fields(p, broker="fink", origin="lsst")["best.coarse_class"] == expected


@pytest.mark.parametrize("label,status", [(-1,"sentinel"), ("11","error"), (True,"error"), (99,"error")])
def test_fink_codes_are_not_silently_coerced(label, status):
    p = portfolio("fink", "lsst", [("fink", {"best.class": label})])
    assert derive_headline_fields(p, broker="fink", origin="lsst")["best.status"] == status


@pytest.mark.parametrize("reliability", [1,2,3])
def test_sherlock_contextual_headline_is_not_physical_confirmation(reliability):
    p = portfolio("lasair", rows=[("sherlock", {"best.class": "SN", "best.score": reliability})])
    result = derive_headline_fields(p, broker="lasair", origin="ztf")
    assert result["best.coarse_class"] == "supernova"
    assert result["best.basis"] == "contextual"
    assert result["best.candidate_status"] == "candidate"
    assert result["best.native_score"] == reliability
    assert "best.native_probability" not in result


def test_catalogue_class_and_unattributed_class_never_become_candidate_votes():
    p = portfolio("lasair", rows=[("sherlock", {"best.class": "SN"})])
    summary, record = p.records
    for invalid in [replace(record, semantic_type="crossmatch@sherlock:lasair"),
                    replace(record, internal_source=None)]:
        result = derive_headline_fields(replace(p, records=(summary, invalid)), broker="lasair", origin="ztf")
        assert result["best.status"] == "missing"


def test_conflicting_object_identity_cannot_supply_a_headline():
    p = portfolio("lasair", rows=[("sherlock", {"best.class": "SN"})])
    extra = SemanticRecord(InternalRecordId("record:other"), "summary@ztf:lasair",
                           {"identity.object_id": "different-object"})
    result = derive_headline_fields(replace(p, records=p.records + (extra,)), broker="lasair", origin="ztf")
    assert result["best.status"] == "identity_unresolved"
    assert "best.coarse_class" not in result


def test_channel_or_execution_from_another_broker_cannot_supply_a_headline():
    p = portfolio("lasair", rows=[("sherlock", {"best.class": "SN"})])
    summary, record = p.records
    mismatched = replace(record, semantic_type="classification@sherlock:fink")
    assert derive_headline_fields(replace(p, records=(summary, mismatched)), broker="lasair", origin="ztf")["best.status"] == "missing"
    assert derive_headline_fields(p, broker="alerce", origin="ztf")["best.status"] == "missing"


def test_delivery_survey_is_not_classifier_input_survey():
    p = portfolio("antares", rows=[("superphot_plus", {"best.class": "SN Ibc"})])
    assert derive_headline_fields(p, broker="antares", origin="ztf")["best.status"] == "input_scope_unresolved"
    explicit = portfolio("antares", rows=[("superphot_plus", {"best.class": "SN Ibc", "provenance.input_survey": "ztf"})])
    assert derive_headline_fields(explicit, broker="antares", origin="ztf")["best.coarse_class"] == "supernova"
    assert derive_headline_fields(p, broker="antares", origin="lsst")["best.status"] == "headline_unresolved"


def test_frozen_alerce_lsst_probability_capture_uses_pinned_model():
    payload = json.loads((ROOT / "tests/fixtures/alerce/lsst/query_probabilities.json").read_text())
    execution = ExecutionResult(payload=payload, execution_provenance=InternalExecutionProvenance(
        InternalExecutionId("capture:alerce"), "alerce", "lsst", "query_probabilities",
        params={"oid": "170587117485817955"},
    ))
    p, = build_portfolios_from_execution(execution)
    result = derive_headline_fields(p, broker="alerce", origin="lsst")
    assert result["best.native_class"] == "SN"
    assert result["best.native_probability"] == 0.76939845
    assert result["best.source_version"] == 202


def test_policy_hash_changes_with_mapping_and_no_prior_result_is_mutated():
    p = portfolio(rows=[("stamp_classifier", ranked("SN"))])
    policy = load_policy("alerce", "ztf")
    first = derive_headline_fields(p, broker="alerce", origin="ztf", policy=policy)
    snapshot = deepcopy(first)
    changed = deepcopy(policy)
    changed["mapping_version"] = "coarse-v2"
    second = derive_headline_fields(p, broker="alerce", origin="ztf", policy=changed)
    assert first == snapshot
    assert first["best.policy_digest"] != second["best.policy_digest"]


def test_malformed_policy_is_not_treated_as_absent_evidence():
    policy = load_policy("alerce", "ztf")
    policy["vocabulary"].append(dict(policy["vocabulary"][0]))
    with pytest.raises(HeadlinePolicyError, match="duplicate"):
        validate_policy(policy)


def test_policy_location_cannot_escape_provider_directory():
    with pytest.raises(HeadlinePolicyError):
        load_policy("../alerce", "ztf")
