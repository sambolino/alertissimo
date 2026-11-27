"""Offline status contracts: native rows remain measurements and unsplit points."""

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
)
from alertissimo.data_layer.runtime.record_builder import build_portfolios_from_execution


FIXTURES = Path(__file__).parent / "fixtures"


def _read(broker, survey, filename):
    return json.loads((FIXTURES / broker / survey / filename).read_text(encoding="utf-8"))


def _normalize(broker, survey, endpoint, payload):
    execution = ExecutionResult(
        payload=payload,
        execution_provenance=InternalExecutionProvenance(
            internal_execution_id=InternalExecutionId("execution:observation-status"),
            broker=broker,
            origin=survey,
            endpoint=endpoint,
        ),
    )
    return build_portfolios_from_execution(execution)


def _views(portfolios, broker, survey):
    measurements = []
    points = []
    for portfolio in portfolios:
        for record in portfolio.records:
            if record.semantic_type == f"measurement@{survey}:{broker}":
                measurements.append(record.fields)
                assert record.internal_source is not None
            elif record.semantic_type == f"lightcurve@{survey}:{broker}":
                points.extend(record.fields.get("points", ()))
    return measurements, points


def _status(row):
    values = [value for key, value in row.items()
              if key.startswith("photometry.") and key.endswith(".upper_limit")]
    assert len(values) <= 1
    assert not values or type(values[0]) is bool
    return values[0] if values else None


def _case(broker, survey):
    if broker == "alerce":
        payload = _read(broker, survey, "query_lightcurve.json")
        expected = [False] * len(payload["detections"])
        if survey == "ztf":
            expected += [True] * len(payload["non_detections"])
        return "query_lightcurve", payload, expected
    if broker == "fink":
        if survey == "ztf":
            payload = _read(broker, survey, "objects_withupperlim.json")
            expected = [{"valid": False, "upperlim": True}.get(row.get("d:tag"))
                        for row in payload]
            return "objects", payload, expected
        payload = _read(broker, survey, "sources.json")
        return "sources", payload, [False] * len(payload)
    if broker == "lasair":
        if survey == "ztf":
            payload = _read(broker, survey, "lightcurves_ZTF23aamxeqf.json")
            expected = [False if "candid" in row else True
                        for row in payload[0]["candidates"]]
            return "lightcurves", payload, expected
        payload = _read(broker, survey, "object.json")
        return "object", payload, [False] * len(payload["diaSourcesList"])
    endpoint = f"get_by_{'ztf_object' if survey == 'ztf' else 'lsst_dia_object'}_id"
    payload = _read(broker, survey, endpoint + ".json")
    # The SDK captures locus and alerts separately; reassemble its declared response.
    payload["alerts"] = _read(broker, survey, "alerts.json")
    expected = [({1: False, 2: True}.get(row["properties"].get("ant_survey"))
                 if survey == "ztf" else False) for row in payload["alerts"]]
    return endpoint, payload, expected


@pytest.mark.parametrize("broker", ["alerce", "fink", "lasair", "antares"])
@pytest.mark.parametrize("survey", ["ztf", "lsst"])
def test_native_fixture_status_agrees_between_measurements_and_points(broker, survey):
    endpoint, payload, expected = _case(broker, survey)
    before = deepcopy(payload)
    measurements, points = _views(_normalize(broker, survey, endpoint, payload), broker, survey)
    # Forced-only measurement epochs have no ordinary photometry branch.
    ordinary = [row for row in measurements if any(key.startswith("photometry.") for key in row)]
    assert len(ordinary) == len(expected)
    assert len(points) == len(expected)
    assert Counter(map(_status, ordinary)) == Counter(expected)
    assert Counter(map(_status, points)) == Counter(expected)
    assert payload == before  # Native evidence is not edited to assign status.
    if broker == "lasair" and survey == "ztf":
        assert Counter(expected) == {False: 2, True: 19}


def test_fink_badquality_and_absent_tags_remain_unknown():
    row = _read("fink", "ztf", "objects_withupperlim.json")[0]
    payload = []
    for index, tag in enumerate(("valid", "upperlim", "badquality", None)):
        copy = dict(row, **{"i:jd": 2460000.5 + index})
        copy.pop("d:tag", None)
        if tag is not None:
            copy["d:tag"] = tag
        payload.append(copy)
    measurements, points = _views(_normalize("fink", "ztf", "objects", payload), "fink", "ztf")
    assert list(map(_status, measurements)) == [False, True, None, None]
    assert list(map(_status, points)) == [False, True, None, None]


@pytest.mark.parametrize("broker", ["alerce", "fink", "lasair", "antares"])
def test_lsst_detection_status_does_not_depend_on_magnitude_or_flux_sign(broker):
    endpoint, payload, _ = _case(broker, "lsst")
    if broker == "alerce":
        rows = payload["detections"]
    elif broker == "fink":
        rows = payload
    elif broker == "lasair":
        rows = payload["diaSourcesList"]
    else:
        rows = [row["properties"] for row in payload["alerts"]]
    for row in rows:
        for key in list(row):
            if key in ("magpsf", "ant_mag", "ant_magerr") or key.endswith(("_mag", "_magerr")):
                row[key] = None
            if key.lower().endswith("psfflux"):
                row[key] = -10.0
    measurements, points = _views(_normalize(broker, "lsst", endpoint, payload), broker, "lsst")
    ordinary = [row for row in measurements if any(key.startswith("photometry.") for key in row)]
    assert ordinary and points
    assert all(_status(row) is False for row in ordinary)
    assert all(_status(row) is False for row in points)
    forced_only = [row for row in measurements
                   if any(key.startswith("forced_photometry.") for key in row)
                   and not any(key.startswith("photometry.") for key in row)]
    assert all(_status(row) is None for row in forced_only)


def test_lasair_object_capture_retains_all_twenty_one_measurements():
    payload = _read("lasair", "ztf", "object_ZTF23aamxeqf.json")
    measurements, points = _views(_normalize("lasair", "ztf", "object", payload), "lasair", "ztf")
    assert len(measurements) == 21
    assert Counter(map(_status, measurements)) == {False: 2, True: 19}
    # Status mapping alone must not manufacture a new lightcurve product on lookup.
    assert not points


@pytest.mark.parametrize("endpoint", ["lightcurves", "object", "objects"])
def test_lasair_rich_limit_never_becomes_a_psf_measurement(endpoint):
    payload = _read("lasair", "ztf", "object_rich_limit_synthetic.json")
    (row,) = payload["candidates"]
    assert "candid" not in row and row["magpsf"] == row["diffmaglim"]
    measurements, points = _views(
        _normalize("lasair", "ztf", endpoint, payload if endpoint == "object" else [payload]),
        "lasair", "ztf",
    )
    assert len(measurements) == 1
    assert len(points) == (1 if endpoint == "lightcurves" else 0)
    for fields in [*measurements, *points]:
        assert fields["photometry.g.upper_limit"] is True
        assert fields["photometry.g.limit.mag"] == row["diffmaglim"]
        assert "photometry.g.psf.mag" not in fields
        assert "photometry.g.psf.mag.error" not in fields


@pytest.mark.parametrize("candid", [None, 123])
def test_lasair_candid_controls_copied_detection_fields_and_limit_precedence(candid):
    payload = _read("lasair", "ztf", "object_rich_limit_synthetic.json")
    row = payload["candidates"][0]
    row.update(candid=candid, ra=10.0, dec=20.0, drb=0.99, isdiffpos="t",
               ssnamenr="Example", ssdistnr=1.5)
    measurements, points = _views(_normalize("lasair", "ztf", "lightcurves", [payload]), "lasair", "ztf")
    assert len(measurements) == len(points) == 1
    for fields in [*measurements, *points]:
        assert fields["photometry.g.upper_limit"] is (candid is None)
        assert fields["photometry.g.limit.mag"] == row["diffmaglim"]
        if candid is None:
            assert "photometry.g.psf.mag" not in fields
            assert "photometry.g.psf.mag.error" not in fields
            assert "quality.real_bogus" not in fields
        else:
            assert fields["photometry.g.psf.mag"] == row["magpsf"]
            assert fields["photometry.g.psf.mag.error"] == row["sigmapsf"]
            assert fields["quality.real_bogus"] == 0.99
    for field in ("position.ra", "position.dec", "image_metrics.is_positive",
                  "solar_system.mpc_match.identity.object_id", "solar_system.mpc_match.separation.total"):
        assert (field in measurements[0]) is (candid is not None)


@pytest.mark.parametrize("broker,endpoint,filename", [
    ("alerce", "query_forced_photometry", "query_forced_photometry.json"),
    ("fink", "fp", "fp.json"),
])
def test_lsst_forced_only_payload_does_not_acquire_an_ordinary_status(broker, endpoint, filename):
    payload = _read(broker, "lsst", filename)
    measurements, points = _views(_normalize(broker, "lsst", endpoint, payload), broker, "lsst")
    assert measurements and not points
    assert all(any(key.startswith("forced_photometry.") for key in row) for row in measurements)
    assert all(not any(key.startswith("photometry.") for key in row) for row in measurements)


@pytest.mark.parametrize("survey,endpoint,expected", [
    ("ztf", "query_detections", False),
    ("ztf", "query_non_detections", True),
    ("lsst", "query_detections", False),
])
def test_alerce_standalone_epoch_arrays_have_the_same_status_rule(survey, endpoint, expected):
    payload = _read("alerce", survey, endpoint + ".json")[:1]
    measurements, points = _views(_normalize("alerce", survey, endpoint, payload), "alerce", survey)
    assert len(measurements) == 1
    assert _status(measurements[0]) is expected
    assert not points  # Adding a status does not create a new series product.


@pytest.mark.parametrize("gates,expected", [
    ({"candid": 1, "flags": {"usable": True}}, True),
    ({"candid": 0, "flags": {"usable": False}}, True),
    ({"candid": "", "flags": {"usable": ""}}, True),
    ({"flags": {"usable": True}}, False),
    ({"candid": None, "flags": {"usable": True}}, False),
    ({"candid": 1, "flags": {"usable": None}}, False),
    ({"candid": 1}, False),
])
def test_requires_checks_all_same_row_fields_for_presence_and_non_null(tmp_path, gates, expected):
    semantic = "measurement@ztf:lasair.photometry.g.psf.mag"
    document = {
        "broker": "lasair", "origin": "ztf",
        "payloads": {"rows": {"endpoint": "object", "path": "candidates[]",
                              "object_partition": {"mode": "single"}}},
        "mappings": {
            semantic: ["rows#magpsf"],
            "measurement@ztf:lasair.time.mjd": ["rows#mjd"],
            "measurement@ztf:lasair.identity.source_id": ["rows#candid"],
            "measurement@ztf:lasair.quality.real_bogus": ["rows#flags.usable"],
        },
        "transforms": {semantic: {"rows#magpsf": {
            "type": "to_float", "requires": ["candid", "flags.usable"],
        }}},
    }
    mapping = tmp_path / "mappings.yaml"
    mapping.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    # Parent-level fields must never satisfy a row-level guard.
    payload = {"candid": 456, "flags": {"usable": True},
               "candidates": [dict(gates, magpsf="18.5", mjd=60000.0)]}
    execution = ExecutionResult(
        payload=payload,
        execution_provenance=InternalExecutionProvenance(
            InternalExecutionId("execution:requires"), "lasair", "ztf", "object",
        ),
    )
    (portfolio,) = build_portfolios_from_execution(execution, mappings_path=mapping)
    (record,) = portfolio.records
    assert ("photometry.g.psf.mag" in record.fields) is expected
    if expected:
        assert record.fields["photometry.g.psf.mag"] == 18.5
