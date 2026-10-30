"""Reference inputs from immutable captures and explicitly synthetic edge cases."""

from copy import deepcopy
from itertools import count
import json
from pathlib import Path

import pytest
import yaml

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance, InternalRecordId
from alertissimo.data_layer.runtime.record_builder import build_portfolios_from_execution
from alertissimo.data_layer.semantic_model import SemanticPathModel
from alertissimo.orchestration.ir import BooleanPredicate, ComparisonPredicate, PredicateLiteral, SemanticReference
from alertissimo.orchestration.normalization.predicate import evaluate_portfolio_predicate


ROOT = Path(__file__).parents[1]
PROVIDER = ROOT / "alertissimo/data_layer/providers/fink/ztf"
FIXTURES = ROOT / "tests/fixtures/fink/ztf"
PIXEL = "reference_image.nearest_source.pixel_distance"


def build(endpoint, payload):
    ids = count()
    return build_portfolios_from_execution(
        ExecutionResult(payload=payload, execution_provenance=InternalExecutionProvenance(
            InternalExecutionId(f"reference:{endpoint}"), "fink", "ztf", endpoint,
        )),
        mappings_path=PROVIDER / "mappings.yaml",
        record_id_factory=lambda: InternalRecordId(f"reference:record:{next(ids)}"),
        validate_semantic_model=True,
    )


def records(portfolios, semantic_type):
    return [r for p in portfolios for r in p.records if r.semantic_type == semantic_type]


@pytest.mark.parametrize("endpoint,fixture", [
    ("objects", "objects_core"), ("conesearch", "conesearch"), ("latests", "latests"),
    ("anomaly", "anomaly"), ("sso", "sso_core"),
])
def test_each_captured_candidate_contract_preserves_pixel_distance_without_angular_alias(endpoint, fixture):
    row = json.loads((FIXTURES / f"{fixture}.json").read_text())[0]
    before = deepcopy(row)
    detection, = records(build(endpoint, [row]), "detection@ztf:fink")
    assert detection.get(PIXEL) == row["i:distnr"]
    assert "reference_image.nearest_source.separation.total" not in detection.fields
    assert detection.internal_source.payload_key == endpoint
    assert detection.internal_source.payload_index == 0
    assert row == before


def test_reference_inputs_keep_their_capture_row_and_reported_count():
    payload = json.loads((FIXTURES / "objects_core.json").read_text())
    portfolios = build("objects", payload)
    detections = records(portfolios, "detection@ztf:fink")
    detection = next(r for r in detections if r.internal_source.payload_index == 0)
    ps1 = next(r for r in records(portfolios, "crossmatch@panstarrs:fink")
               if r.internal_source.payload_index == 0)
    row = payload[0]
    assert detection.internal_source == ps1.internal_source
    assert detection.get("identity.source_id") == row["i:candid"]
    assert detection.get("time.mjd") == pytest.approx(row["i:jd"] - 2400000.5)
    band = {1: "g", 2: "r", 3: "i"}[row["i:fid"]]
    assert detection.get(f"photometry.{band}.psf.mag") == row["i:magpsf"]
    assert detection.get(f"photometry.{band}.psf.mag.error") == row["i:sigmapsf"]
    assert detection.get(PIXEL) == row["i:distnr"]
    assert detection.get("image_metrics.is_positive") is True
    assert ps1.get("separation.total") == row["i:distpsnr1"]
    assert ps1.get("classification.assessment.star_galaxy.score") == row["i:sgscore1"]
    summaries = records(portfolios, "summary@ztf:fink")
    assert {r.get("detection_count") for r in summaries if r.get("detection_count") is not None} == {17}
    assert len(detections) == 14


@pytest.mark.parametrize("value", [0.0, -999.0, None])
def test_pixel_mapping_keeps_zero_sentinel_and_null_without_changing_subtraction_sign(value):
    row = {"i:objectId": "ZTF-synthetic", "i:candid": 123, "i:jd": 2459000.5,
           "i:fid": 1, "i:magpsf": 20.0, "i:distnr": value, "i:isdiffpos": "f"}
    before = deepcopy(row)
    detection, = records(build("objects", [row]), "detection@ztf:fink")
    assert detection.get(PIXEL) == value
    assert detection.get("image_metrics.is_positive") is False
    assert "reference_image.nearest_source.separation.total" not in detection.fields
    assert row == before


def test_missing_pixel_distance_is_not_synthesized_from_other_distances():
    row = {"i:objectId": "ZTF-synthetic", "i:candid": 123, "i:jd": 2459000.5,
           "i:fid": 1, "i:magpsf": 20.0, "i:distpsnr1": 0.1}
    detection, = records(build("objects", [row]), "detection@ztf:fink")
    assert PIXEL not in detection.fields


def test_valid_nonnegative_pixel_filter_selects_candidates_and_keeps_all_their_measurements():
    def row(oid, candid, distance):
        return {"i:objectId": oid, "i:candid": candid, "i:jd": 2459000.5 + candid,
                "i:fid": 1, "i:magpsf": 20.0, "i:distnr": distance}
    portfolios = build("objects", [row("A", 1, 0.1), row("A", 2, 10.0), row("B", 3, -999.0)])
    predicate = BooleanPredicate(operator="and", operands=tuple(
        ComparisonPredicate(
            left=SemanticReference(semantic_type="detection", producer="ztf", channel="fink", field_path=PIXEL),
            operator=operator, right=PredicateLiteral(value=value),
        ) for operator, value in [(">=", 0), ("<=", 0.5)]
    ))
    selected = tuple(p for p in portfolios if evaluate_portfolio_predicate(p, predicate))
    assert len(selected) == 1
    assert sorted(r.get(PIXEL) for r in records(selected, "detection@ztf:fink")) == [0.1, 10.0]


def test_new_mapping_retires_only_the_pixel_distance_exclusions():
    mapping = yaml.safe_load((PROVIDER / "mappings.yaml").read_text())
    debt = yaml.safe_load((PROVIDER / "unmapped_fields.yaml").read_text())
    mapped = set(mapping["mappings"][f"detection@ztf:fink.{PIXEL}"])
    assert mapped == {f"{endpoint}#i:distnr" for endpoint in ("objects", "conesearch", "latests", "anomaly", "sso")}
    excluded = {next(iter(entry)) for entry in debt["unmapped"]}
    assert not mapped & excluded
    assert {"objects#i:objectidps2", "objects#i:objectidps3"} <= excluded
    assert SemanticPathModel.from_ontology().is_valid(f"detection@ztf:fink.{PIXEL}")
