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
    assert result["best.taxon"] == (2222,)
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
    assert result["best.taxon"] == (2332,)


def test_broker_selected_summary_resolves_historical_probability_versions():
    p = portfolio(rows=[("lc_classifier", ranked("SNIa", version="old")),
                        ("lc_classifier", ranked("SNII", version="new")),
                        ("lc_classifier", {"best.class": "SNIbc", "best.probability": 0.525456})])
    result = derive_headline_fields(p, broker="alerce", origin="ztf")
    assert result["best.native_class"] == "SNIbc"
    assert result["best.source_version"] is None
    assert result["best.selected_record_ids"] == ("record:2",)


@pytest.mark.parametrize("second_label", ["SNIa", "SNII"])
def test_label_contract_versions_agree_only_on_identical_labels(second_label):
    p = portfolio(rows=[("lc_classifier", ranked("SNIa", version="1.0")),
                        ("lc_classifier", ranked(second_label, version="99.0")),
                        ("stamp_classifier", ranked("SN"))])
    result = derive_headline_fields(p, broker="alerce", origin="ztf")
    if second_label == "SNIa":
        assert result["best.status"] == "available"
        assert result["best.taxon"] == (2222,)
        assert result["best.source_version"] == ('"1.0"', '"99.0"')
    else:
        assert result["best.status"] == "conflict"
        assert "best.taxon" not in result
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
    assert "best.taxon" not in result


def test_duplicate_witnesses_do_not_choose_a_metric():
    p = portfolio(rows=[("stamp_classifier", ranked("SN", probability=0.2)),
                        ("stamp_classifier", ranked("SN", probability=0.8))])
    result = derive_headline_fields(p, broker="alerce", origin="ztf")
    assert result["best.taxon"] == (2220, 2242, 2246)
    assert "best.native_probability" not in result
    assert result["best.selected_record_ids"] == ("record:0", "record:1")


@pytest.mark.parametrize("version", [202, "2.0.2"])
def test_lsst_pinned_method_and_explicit_native_version_identifiers(version):
    p = portfolio(origin="lsst", rows=[
        ("stamp_classifier_rubin_beta", ranked("AGN", version=201, probability=0.99)),
        ("stamp_classifier_rubin_beta_20260421", ranked("SN", version=version, probability=0.1)),
    ])
    result = derive_headline_fields(p, broker="alerce", origin="lsst")
    assert result["best.taxon"] == (2220, 2242, 2246)
    assert result["best.source_version"] == version


@pytest.mark.parametrize("version", [None, "202", 203, "2.0.3"])
def test_unreviewed_lsst_versions_abstain(version):
    p = portfolio(origin="lsst", rows=[("stamp_classifier_rubin_beta_20260421", ranked("SN", version=version))])
    result = derive_headline_fields(p, broker="alerce", origin="lsst")
    assert result["best.status"] == "unsupported_version"
    assert "best.taxon" not in result


def test_new_classifier_never_displaces_pinned_method():
    p = portfolio(origin="lsst", rows=[("stamp_classifier_rubin_beta_20990101", ranked("SN", version="100"))])
    assert derive_headline_fields(p, broker="alerce", origin="lsst")["best.status"] == "missing"


def test_fink_latest_uses_exact_row_linked_observation_not_score_or_array_order():
    p = portfolio("fink", rows=[("fink", {"best.class": "SN candidate"}),
                                 ("fink", {"best.class": "Microlensing candidate"})], times=[60002, 60001])
    result = derive_headline_fields(p, broker="fink", origin="ztf")
    assert result["best.taxon"] == (2220, 2242, 2246)
    assert result["best.observation_mjd"] == 60002


def test_fink_missing_observation_order_and_ties_abstain():
    rows = [("fink", {"best.class": "SN candidate"}), ("fink", {"best.class": "Microlensing candidate"})]
    for times, status in [([60002, None], "observation_order_unresolved"), ([60002, 60002], "conflict")]:
        result = derive_headline_fields(portfolio("fink", rows=rows, times=times), broker="fink", origin="ztf")
        assert result["best.status"] == status
        assert "best.taxon" not in result


def test_fink_full_catalogue_and_unknown_sentinel_are_accounted_separately():
    policy = load_policy("fink", "ztf")
    # 369 published labels, of which Ambiguous is a sentinel; Unknown is additional.
    assert len(policy["vocabulary"]) == 721  # 368 original + 358 bare - 5 duplicates
    assert len(policy["sentinels"]) == 2
    for label in ["Unknown", "Ambiguous"]:
        result = derive_headline_fields(portfolio("fink", rows=[("fink", {"best.class": label})]), broker="fink", origin="ztf")
        assert result["best.status"] == "sentinel"
    label = "(TNS) SN Ia"
    assert any(v["label"] == label for v in policy["vocabulary"])
    result = derive_headline_fields(portfolio("fink", rows=[("fink", {"best.class": label})]), broker="fink", origin="ztf")
    assert result["best.scope"] == "catalogue_association"
    assert "best.taxon" not in result


@pytest.mark.parametrize("code,expected", [(11,(2220,)), (12,(2230,)), (13,(2240,)), (21,(2320,)), (22,(2332,))])
def test_fink_lsst_codes_have_finite_explicit_meanings(code, expected):
    p = portfolio("fink", "lsst", [("fink", {"best.class": code, "assessment.crossmatch.class": "AGN"})])
    assert derive_headline_fields(p, broker="fink", origin="lsst")["best.taxon"] == expected


@pytest.mark.parametrize("label,status", [(-1,"sentinel"), ("11","error"), (True,"error"), (99,"error")])
def test_fink_codes_are_not_silently_coerced(label, status):
    p = portfolio("fink", "lsst", [("fink", {"best.class": label})])
    assert derive_headline_fields(p, broker="fink", origin="lsst")["best.status"] == status


@pytest.mark.parametrize("reliability", [1,2,3])
def test_sherlock_contextual_headline_is_not_physical_confirmation(reliability):
    p = portfolio("lasair", rows=[("sherlock", {"best.class": "SN", "best.score": reliability})])
    result = derive_headline_fields(p, broker="lasair", origin="ztf")
    assert result["best.taxon"] == (2220, 2242, 2246)
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
    assert "best.taxon" not in result


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
    assert derive_headline_fields(explicit, broker="antares", origin="ztf")["best.taxon"] == (2223,)
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
    changed["mapping_version"] = "elasticc-v2"
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


def test_elasticc_dictionary_is_exact_and_local_extension_is_marked():
    from alertissimo.data_layer.runtime.classification_headline import load_taxonomy, validate_taxonomy
    taxonomy = load_taxonomy()
    validate_taxonomy(taxonomy)
    groups = {
        None: {0: "Meta", 1000: "Static", 2000: "Variable"},
        0: {100: "Meta/Other", 200: "Residual", 300: "NotClassified"},
        1000: {1100: "Static/Other"},
        2000: {2100: "Variable/Other", 2200: "Non-Recurring", 2300: "Recurring"},
        2200: {2210: "Non-Recurring/Other", 2220: "SN-like", 2230: "Fast", 2240: "Long"},
        2220: {2221: "SN-like/Other", 2222: "Ia", 2223: "Ib/c", 2224: "II", 2225: "Iax", 2226: "91bg"},
        2230: {2231: "Fast/Other", 2232: "KN", 2233: "M-dwarf Flare", 2234: "Dwarf Novae", 2235: "uLens"},
        2240: {2241: "Long/Other", 2242: "SLSN", 2243: "TDE", 2244: "ILOT", 2245: "CART", 2246: "PISN"},
        2300: {2310: "Recurring/Other", 2320: "Periodic", 2330: "Non-Periodic"},
        2320: {2321: "Periodic/Other", 2322: "Cepheid", 2323: "RR Lyrae", 2324: "Delta Scuti", 2325: "EB", 2326: "LPV/Mira"},
        2330: {2331: "Non-Periodic/Other", 2332: "AGN"},
    }
    expected = {(code, name, parent) for parent, children in groups.items() for code, name in children.items()}
    assert {(n["code"], n["name"], n["parent"]) for n in taxonomy["nodes"] if n["origin"] == "elasticc"} == expected
    extension = [n for n in taxonomy["nodes"] if n["code"] not in {row[0] for row in expected}]
    assert {(n["code"], n["parent"]) for n in extension} == {
        (9000, None), (9100, 9000), (9200, 9000), (9210, 9200), (9220, 9200), (9300, 9000),
    }
    assert all(n["origin"] == "alertissimo" and 9000 <= n["code"] <= 9399 for n in extension)
    used = {n["code"]: n["used_for"] for n in taxonomy["nodes"] if n.get("used_for", "unused") != "unused"}
    assert used == {2321: "other periodic variable stars", 2331: "young stellar objects", 2231: "classical novae"}
    aliases = {a["alias"] for a in taxonomy["aliases"]}
    assert "nova" not in aliases
    assert {str(n["code"]) for n in taxonomy["nodes"]} <= aliases


@pytest.mark.parametrize("defect", ["duplicate_code", "missing_parent", "cycle", "duplicate_alias", "unknown_alias_code", "other_meaning"])
def test_malformed_taxonomy_is_a_maintainer_error(defect):
    from alertissimo.data_layer.runtime.classification_headline import load_taxonomy, validate_taxonomy
    taxonomy = deepcopy(load_taxonomy())
    if defect == "duplicate_code":
        taxonomy["nodes"].append(deepcopy(taxonomy["nodes"][0]))
    elif defect == "missing_parent":
        taxonomy["nodes"][0]["parent"] = -123
    elif defect == "cycle":
        taxonomy["nodes"][0]["parent"] = 100
    elif defect == "duplicate_alias":
        taxonomy["aliases"].append({"alias": "  SNIA  ", "codes": [2222]})
    elif defect == "unknown_alias_code":
        taxonomy["aliases"][0]["codes"] = [-123]
    else:
        next(n for n in taxonomy["nodes"] if n["code"] == 2231).pop("used_for")
    with pytest.raises(HeadlinePolicyError):
        validate_taxonomy(taxonomy)


def test_policy_cannot_use_unused_other_or_catalogue_codes():
    policy = load_policy("alerce", "ztf")
    policy["vocabulary"][0]["codes"] = [2221]
    with pytest.raises(HeadlinePolicyError, match="used_for"):
        validate_policy(policy)
    policy = load_policy("fink", "ztf")
    policy["vocabulary"][0]["codes"] = [2222]
    with pytest.raises(HeadlinePolicyError, match="catalogue"):
        validate_policy(policy)


@pytest.mark.parametrize("label", ["RRLyr", "EB*", "EB*_Candidate", "CataclyV*", "WD*_Candidate"])
def test_bare_fink_catalogue_labels_are_recognized_without_votes(label):
    result = derive_headline_fields(portfolio("fink", rows=[("fink", {"best.class": label})]), broker="fink", origin="ztf")
    assert result["best.status"] == "recognized_no_proposition"
    assert result["best.scope"] == "catalogue_association"
    assert "best.taxon" not in result


@pytest.mark.parametrize("record,query,expected", [
    ((2222,), "snia", True), ((2222,), "snii", False), ((2222,), "supernova", True),
    ((2220,), "snia", None), ((2220,), "supernova", True),
    ((2220, 2242, 2246), "supernova", True), ((2220, 2243, 2332), "tde", None),
    ((2220, 2243, 2332), "solar_system", False), ((9000,), "satellite", None),
    ((9000,), "solar_system", None), ((100,), "meta", True),
    ((2231,), "classical_nova", True), ((2331,), "yso", True),
])
def test_taxonomy_support_opposition_and_unknown(record, query, expected):
    from alertissimo.data_layer.runtime.classification_headline import compare_taxa, resolve_taxon
    codes = resolve_taxon(query)
    assert compare_taxa(record, codes) is expected
    assert compare_taxa(record, codes, "!=") is (None if expected is None else not expected)


def _fixture_labels(broker, origin, methods):
    """Inspect captured native outputs, including nested and unselected rank rows."""
    def labels(value):
        if isinstance(value, list):
            for item in value:
                yield from labels(item)
        elif isinstance(value, dict):
            if broker == "alerce" and value.get("classifier_name", value.get("classifier")) in methods:
                label = value.get("class_name", value.get("class"))
                if label is not None:
                    yield label
            if broker == "fink":
                keys = ("v:classification",) if origin == "ztf" else ("f:main_label_classifier", "f:clf_cats_class")
                for key in keys:
                    if value.get(key) is not None:
                        yield value[key]
            if broker == "antares" and value.get("superphot_plus_class") is not None:
                yield value["superphot_plus_class"]
            if broker == "lasair":
                sherlock = value.get("sherlock", {})
                if isinstance(sherlock, dict) and sherlock.get("classification") is not None:
                    yield sherlock["classification"]
                if "objectId" in value and value.get("classification") is not None:
                    yield value["classification"]
                # Flattened SQL and Sherlock classification endpoint shapes.
                if value.get("sherlock_classification") is not None:
                    yield value["sherlock_classification"]
                classifications = value.get("classifications", {})
                if isinstance(classifications, dict):
                    for output in classifications.values():
                        if isinstance(output, list) and output:
                            yield output[0]
            for item in value.values():
                yield from labels(item)
    for path in (ROOT / "tests/fixtures" / broker / origin).rglob("*.json"):
        if path.name.endswith(".request.json"):
            continue
        try:
            payload = json.loads(path.read_text())
        except (ValueError, UnicodeError):
            continue  # Captured HTTP-error bodies are not classification outputs.
        for label in labels(payload):
            yield path, label


@pytest.mark.parametrize("broker,origin", [(b, o) for b in ("alerce", "fink", "lasair", "antares") for o in ("ztf", "lsst")])
def test_all_fixture_outputs_are_mapped_and_alerce_vocabulary_is_reachable(broker, origin):
    policy = load_policy(broker, origin)
    if not policy["enabled"]:
        return
    methods = {m["producer"] for m in policy["methods"]}
    mapped = {json.dumps(r["label"]) for r in policy["vocabulary"]}
    sentinels = {json.dumps(v) for v in policy["sentinels"]}
    seen = set()
    for path, label in _fixture_labels(broker, origin, methods):
        key = json.dumps(label)
        assert key in mapped | sentinels, (path, label)
        seen.add(key)
    if broker == "alerce":
        assert seen and mapped <= seen
    # ANTARES/ZTF captures currently contain no Superphot+ label. The drift
    # check covers any that appear later without fabricating fixture evidence.


@pytest.mark.parametrize("broker,origin", [(b, o) for b in ("alerce", "fink", "lasair", "antares") for o in ("ztf", "lsst")])
def test_every_reviewed_candidate_mapping_is_exact(broker, origin):
    sn, vs, cv = {2220, 2242, 2246}, {2320, 2233, 2234, 2331}, {2234, 2231}
    mappings = {
        "alerce": {
            "SNIa": {2222}, "SNIbc": {2223}, "SNII": {2224}, "SLSN": {2242}, "SN": sn,
            "QSO": {2332}, "AGN": {2332}, "Blazar": {2332}, "CV/Nova": cv, "YSO": {2331},
            "LPV": {2326}, "E": {2325}, "DSCT": {2324}, "RRL": {2323}, "CEP": {2322},
            "Periodic-Other": {2321}, "VS": vs, "asteroid": {9220}, "bogus": {1000},
        },
        "fink": {
            "SN candidate": sn, "Early SN Ia candidate": {2222}, "SLSN candidate": {2242},
            "Kilonova candidate": {2232}, "Microlensing candidate": {2235},
            "Solar System candidate": {9200}, "Solar System MPC": {9200},
            "(CTA) Blazar high state": {2332}, "(CTA) Blazar low state": {2332}, "Tracklet": {9000},
        },
        "lasair": {"SN": sn, "AGN": {2332}, "VS": vs, "CV": cv, "BS": {1000, 2320, 2233}, "NT": {2332, 2243, 2220}},
        "antares": {"SN Ia": {2222}, "SN II": {2224}, "SN IIn": {2224}, "SN Ibc": {2223}, "SLSN-I": {2242}},
    }
    expected = mappings[broker]
    if origin == "lsst":
        if broker == "alerce":
            expected = {k: expected[k] for k in ("AGN", "SN", "VS", "asteroid", "bogus")}
        elif broker == "fink":
            expected = {11: {2220}, 12: {2230}, 13: {2240}, 21: {2320}, 22: {2332}}
        elif broker == "antares":
            expected = {}
    policy = load_policy(broker, origin)
    assert {r["label"]: set(r["codes"]) for r in policy["vocabulary"] if r["scope"] == "candidate"} == expected
    assert all(r["codes"] is None for r in policy["vocabulary"] if r["scope"] == "catalogue_association")
    assert policy["mapping_version"] == "elasticc-v1"
    assert policy["policy_id"].endswith("-v2")
    if (broker, origin) == ("fink", "ztf"):
        rows = {r["label"]: r for r in policy["vocabulary"]}
        for label, row in rows.items():
            if label.startswith(("(SIMBAD) ", "(TNS) ")):
                bare = rows[label.split(" ", 1)[1]]
                assert bare["scope"] == "catalogue_association" and bare["codes"] is None
