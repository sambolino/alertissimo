"""Regression coverage for the authoritative ALeRCE LSST contract."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests/fixtures/alerce/lsst"
MAPPINGS = ROOT / "alertissimo/data_layer/providers/alerce/lsst/mappings.yaml"
ENDPOINTS = ROOT / "alertissimo/data_layer/providers/alerce/lsst/endpoints.yaml"


def _fixture(endpoint: str):
    return json.loads((FIXTURES / f"{endpoint}.json").read_text(encoding="utf-8"))


def test_query_probabilities_contract_does_not_advertise_classifier_filter():
    endpoint = yaml.safe_load(ENDPOINTS.read_text(encoding="utf-8"))["endpoints"][
        "query_probabilities"
    ]

    assert "classifier" not in endpoint["params"]
    assert "classifier" not in endpoint["server_filters"]


def test_captured_psf_flags_are_json_booleans():
    detections = _fixture("query_detections")
    lightcurve_detections = _fixture("query_lightcurve")["detections"]

    for row in [*detections, *lightcurve_detections]:
        for field in (
            "psfFlux_flag",
            "psfFlux_flag_edge",
            "psfFlux_flag_noGoodPixels",
        ):
            assert type(row[field]) is bool


def test_query_objects_classification_stays_on_summary_identified_by_oid():
    mappings = yaml.safe_load(MAPPINGS.read_text(encoding="utf-8"))["mappings"]
    identity_path = "summary@lsst:alerce.identity.object_id"
    class_path = "summary@lsst:alerce.classification.best.class"
    classifier_path = "summary@lsst:alerce.classification.best.classifier"
    probability_path = "summary@lsst:alerce.classification.best.probability"

    assert "query_objects#oid" in mappings[identity_path]
    assert "query_objects#class_name" in mappings[class_path]
    assert "query_objects#classifier_name" in mappings[classifier_path]
    assert "query_objects#probability" in mappings[probability_path]

    first = _fixture("query_objects")[0]
    assert first["oid"] == 170587117485817955
    assert first["class_name"] == "SN"
    assert first["classifier_name"] == "stamp_classifier_rubin_beta_20260421"
    assert first["probability"] == 0.76939845
