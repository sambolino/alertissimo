"""Consumer ownership and scientific-evidence access; offline only."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from alertissimo.api import execute_dsl
from alertissimo.data_layer.execution import RegistryEndpointExecutor, TransportResult
from alertissimo.data_layer.presentation import portfolio_lightcurve_dataframe
from alertissimo.data_layer.representations import (
    InternalExecutionId, InternalExecutionProvenance, InternalPortfolioId,
    InternalRecordId, InternalRecordSource, Portfolio, SemanticRecord,
)
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.data_layer.runtime.serialization import portfolio_to_dict, portfolio_to_json
from examples.application_portfolio_access import (
    candidate_identity, classification_records, record_frame, select_candidate,
)


IDS = ("ZTF21abfmbix", "ZTF20acpwljl")
LARGE_ID = 9007199254740993


def candidate(oid, *, origin="ztf", magnitude=19.0):
    fink = InternalExecutionId(f"{origin}:{oid}:fink")
    alerce = InternalExecutionId(f"{origin}:{oid}:forced")
    history = InternalExecutionId(f"{origin}:{oid}:history")
    probabilities = InternalExecutionId(f"{origin}:{oid}:probabilities")
    row = InternalRecordSource(fink, "objects", "[]", 0)
    older = InternalRecordSource(fink, "objects", "[]", 1)
    forced = InternalRecordSource(alerce, "query_forced_photometry", "[]", 0)
    upper = InternalRecordSource(history, "query_lightcurve.non_detections", "non_detections[]", 0)
    class_v1 = InternalRecordSource(probabilities, "query_probabilities", "[]", 0)
    class_v2 = InternalRecordSource(probabilities, "query_probabilities", "[]", 1)

    def record(name, semantic_type, fields, source=row):
        return SemanticRecord(InternalRecordId(f"{origin}:{oid}:{name}"), semantic_type, fields, source)

    return Portfolio(InternalPortfolioId(f"{origin}:{oid}"), records=(
        record("summary", f"summary@{origin}:fink", {
            "identity.object_id": oid, "detection_count": 11, "time.last_mjd": 60002.0,
        }),
        record("old-summary", f"summary@{origin}:fink", {
            "identity.object_id": oid, "detection_count": 8, "time.last_mjd": 60001.0,
        }, older),
        record("ordinary", f"measurement@{origin}:fink", {
            "identity.object_id": oid, "identity.source_id": LARGE_ID,
            "time.mjd": 60002.0, "photometry.g.psf.mag": magnitude,
            "photometry.g.psf.mag.error": 0.1, "quality.real_bogus": 0.97,
        }),
        record("forced", f"measurement@{origin}:alerce", {
            "identity.object_id": oid, "time.mjd": 60003.0,
            "forced_photometry.r.flux": -2.0, "forced_photometry.r.flux.error": 1.0,
        }, forced),
        record("upper", f"measurement@{origin}:alerce", {
            "identity.object_id": oid, "time.mjd": 60004.0,
            "photometry.g.limit.mag": 21.0,
        }, upper),
        # Deliberately put the older assertion first. Order proves no recency.
        record("old-class", "classification@fink", {"best.class": "Unknown"}, older),
        record("new-class", "classification@fink", {"best.class": "SN candidate"}),
        record("v1", "classification@lc_classifier:alerce", {
            "provenance.producer.name": "lc_classifier", "provenance.producer.version": "v1",
            "assessment.SN.class": "SN", "assessment.SN.probability": 0.8,
        }, class_v1),
        record("v2", "classification@lc_classifier:alerce", {
            "provenance.producer.name": "lc_classifier", "provenance.producer.version": "v2",
            "assessment.SN.class": "SN", "assessment.SN.probability": 0.9,
        }, class_v2),
        record("ps1", "crossmatch@panstarrs:fink", {
            "separation.total": 0.3, "classification.assessment.star_galaxy.score": 0.2,
        }),
    ), executions=(
        InternalExecutionProvenance(fink, "fink", origin, "objects", params={"objectId": oid}),
        InternalExecutionProvenance(alerce, "alerce", origin, "query_forced_photometry", params={"oid": oid}),
        InternalExecutionProvenance(history, "alerce", origin, "query_lightcurve", params={"oid": oid}),
        InternalExecutionProvenance(probabilities, "alerce", origin, "query_probabilities", params={"oid": oid}),
    ))


def test_explicit_selection_never_relabels_the_union_or_confuses_surveys():
    a, b = candidate(IDS[0]), candidate(IDS[1], magnitude=17.0)
    same_id_other_survey = candidate(IDS[0], origin="lsst", magnitude=16.0)
    selected = select_candidate((b, same_id_other_survey, a), origin="ztf", object_id=IDS[0])
    assert selected is a
    assert candidate_identity(selected) == ("ztf", IDS[0])
    points = portfolio_lightcurve_dataframe(selected)
    assert points[points["measurement_kind"] == "ordinary"]["value"].tolist() == [19.0]
    exported = json.loads(portfolio_to_json(selected))
    assert exported == portfolio_to_dict(a)
    assert {r["fields"]["identity.object_id"] for r in exported["records"]
            if "identity.object_id" in r["fields"]} == {IDS[0]}


def test_missing_duplicate_and_mixed_candidate_identities_are_explicit_errors():
    a, b = candidate(IDS[0]), candidate(IDS[1])
    with pytest.raises(ValueError, match="found 0"):
        select_candidate((a,), origin="ztf", object_id=IDS[1])
    with pytest.raises(ValueError, match="found 2"):
        select_candidate((a, a), origin="ztf", object_id=IDS[0])
    # Keep the copied record's execution audit valid so the consumer identity
    # check, rather than Portfolio's source-integrity guard, rejects the union.
    mixed = replace(a, records=a.records + (b.records[0],), executions=a.executions + b.executions)
    with pytest.raises(ValueError, match="one candidate identity"):
        candidate_identity(mixed)
    with pytest.raises(ValueError, match="one candidate identity"):
        candidate_identity(Portfolio(InternalPortfolioId("empty")))
    with pytest.raises(ValueError, match="qualified survey/object"):
        candidate_identity(replace(a, records=(replace(a.records[0], semantic_type="summary"),)))


def test_classification_selection_uses_exact_type_version_and_source_not_list_order():
    p = candidate(IDS[0])
    measurement, = p.records_of_type("measurement@ztf:fink")
    for ordered in (p, replace(p, records=tuple(reversed(p.records)))):
        assertions = classification_records(ordered, semantic_type="classification@fink")
        assert {r.get("best.class") for r in assertions} == {"Unknown", "SN candidate"}
        selected, = classification_records(ordered, semantic_type="classification@fink", source=measurement.internal_source)
        assert selected.get("best.class") == "SN candidate"
        v1, = classification_records(ordered, semantic_type="classification@lc_classifier:alerce", version="v1")
        assert v1.get("assessment.SN.probability") == 0.8
        assert classification_records(ordered, semantic_type="classification@lc_classifier:alerce", version="missing") == ()
        assert classification_records(ordered, semantic_type="classification@other:alerce") == ()
    with pytest.raises(ValueError, match="exact qualified"):
        classification_records(p, semantic_type="classification")


def test_views_keep_limits_counts_exact_identifiers_and_auditable_crossmatches():
    p = candidate(IDS[0])
    before = portfolio_to_dict(p)
    frame = record_frame(p, "measurement")
    ordinary = frame[frame["semantic_type"] == "measurement@ztf:fink"].iloc[0]
    assert ordinary["fields.identity.source_id"] == LARGE_ID
    assert isinstance(ordinary["fields.identity.source_id"], int)
    assert ordinary["fields.quality.real_bogus"] == 0.97
    assert ordinary["source.payload_index"] == 0
    ps1, = p.records_of_type("crossmatch@panstarrs:fink")
    assert ps1.internal_source == p.get_record(ordinary["internal_record_id"]).internal_source
    assert p.execution(ps1.internal_source.internal_execution_id).broker == "fink"
    assert record_frame(p, "crossmatch").iloc[0]["fields.separation.total"] == 0.3
    assert frame["fields.photometry.g.limit.mag"].dropna().tolist() == [21.0]
    assert record_frame(p, "summary")["fields.detection_count"].tolist() == [11, 8]
    plotting = portfolio_lightcurve_dataframe(p)
    assert set(plotting["measurement_kind"]) == {"ordinary", "forced"}
    assert plotting[plotting["measurement_kind"] == "forced"]["value"].tolist() == [-2.0]
    assert len(plotting) == 2 and len(frame) == 3  # A limit is not an ordinary detection.
    audited = plotting.merge(frame, left_on="record_id", right_on="internal_record_id", validate="many_to_one")
    assert set(audited["source.internal_execution_id"]) <= {e.internal_execution_id.value for e in p.executions}
    assert portfolio_to_dict(p) == before


@pytest.mark.parametrize("ids", [IDS[:1], IDS], ids=["single-candidate", "multiple-candidates"])
def test_public_dsl_result_exposes_separate_candidates_and_serializes_the_same_evidence(ids):
    capture = json.loads((Path(__file__).parent / "fixtures/fink/ztf/objects_core.json").read_text())
    rows = {}
    for index, oid in enumerate(ids):
        row = deepcopy(capture[0])
        row.update({"i:objectId": oid, "i:candid": LARGE_ID + index,
                    "i:magpsf": 19.0 - index, "v:classification": f"class-{index}",
                    "i:distpsnr1": 0.2 + index, "i:ndethist": 17 + index})
        rows[oid] = row

    class ReplayTransport:
        def __init__(self):
            self.requested = []

        def execute(self, spec, params, headers=None):
            assert (spec.broker, spec.origin, spec.endpoint) == ("fink", "ztf", "objects")
            requested = params["objectId"].split(",")
            assert set(requested) <= set(ids)
            self.requested.extend(requested)
            return TransportResult([deepcopy(rows[oid]) for oid in requested], status_code=200, content_type="application/json")

    transport = ReplayTransport()
    source = f"objects {', '.join(ids)} from ztf via fink\nwith lightcurve via fink\n"
    result = execute_dsl(source, graph=build_capability_graph(),
                         executor=RegistryEndpointExecutor(transports={"rest": transport}), continue_from=None)
    assert {candidate_identity(p) for p in result.portfolios} == {("ztf", oid) for oid in ids}
    assert set(transport.requested) == set(ids)
    serialized = json.loads(result.to_json())
    assert serialized["portfolios"] == [portfolio_to_dict(p) for p in result.portfolios]
    for index, oid in enumerate(ids):
        p = select_candidate(result.portfolios, origin="ztf", object_id=oid)
        ordinary = portfolio_lightcurve_dataframe(p)
        assert set(ordinary["value"]) == {19.0 - index}
        assert {r.get("best.class") for r in classification_records(p, semantic_type="classification@fink")} == {f"class-{index}"}
        assert set(record_frame(p, "measurement")["fields.identity.source_id"]) == {LARGE_ID + index}
        assert {r.get("separation.total") for r in p.records_of_type("crossmatch@panstarrs:fink")} == {0.2 + index}
        assert set(record_frame(p, "summary")["fields.detection_count"]) == {17 + index}
        assert all(e.origin == "ztf" and e.broker == "fink" for e in p.executions)
