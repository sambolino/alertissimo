"""Regression tests against the frozen authenticated Lasair/ZTF capture."""

from __future__ import annotations

import copy
from itertools import count
import json
from pathlib import Path

import pytest

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
    InternalPortfolioId,
    InternalRecordId,
)
from alertissimo.data_layer.runtime.record_builder import (
    build_portfolio_from_execution,
    build_portfolios_from_execution,
)
from tools.audit_payload_mapping_coverage import audit_payload


CAPTURE = (
    Path(__file__).parent
    / "fixtures/lasair/ztf/capture_20260813T110413Z"
)
MAPPINGS = (
    Path(__file__).parents[1]
    / "alertissimo/data_layer/providers/lasair/ztf/mappings.yaml"
)


def _fixture(name: str):
    return json.loads((CAPTURE / f"{name}.json").read_text(encoding="utf-8"))


def _build(endpoint: str, payload):
    execution_id = InternalExecutionId(f"execution:fixture:{endpoint}")
    ids = count()
    return build_portfolio_from_execution(
        ExecutionResult(
            payload=payload,
            execution_provenance=InternalExecutionProvenance(
                internal_execution_id=execution_id,
                broker="lasair",
                origin="ztf",
                endpoint=endpoint,
            ),
        ),
        mappings_path=MAPPINGS,
        internal_portfolio_id=InternalPortfolioId("portfolio:fixture"),
        record_id_factory=lambda: InternalRecordId(f"record:{next(ids)}"),
        validate_semantic_model=True,
    )


def _build_all(endpoint: str, payload):
    execution_id = InternalExecutionId(f"execution:fixture:{endpoint}")
    return build_portfolios_from_execution(
        ExecutionResult(
            payload=payload,
            execution_provenance=InternalExecutionProvenance(
                internal_execution_id=execution_id,
                broker="lasair",
                origin="ztf",
                endpoint=endpoint,
            ),
        ),
        mappings_path=MAPPINGS,
        validate_semantic_model=True,
    )


def _assert_zero_unaccounted(endpoint: str, name: str) -> None:
    report = audit_payload(
        _fixture(name),
        broker="lasair",
        origin="ztf",
        endpoint=endpoint,
        payload_file=str(CAPTURE / f"{name}.json"),
    )
    assert "Unaccounted leaves: 0" in report


def test_capture_records_live_parameter_dependent_shapes() -> None:
    assert _fixture("cone_all") == [
        {"object": "ZTF20acpwljl", "separation": 0.0}
    ]
    assert _fixture("cone_nearest") == {
        "object": "ZTF20acpwljl",
        "separation": 0.0,
    }
    assert _fixture("cone_count") == {"count": 1}
    assert isinstance(_fixture("sherlock_object_full"), dict)
    assert isinstance(_fixture("sherlock_objects_full"), dict)
    assert len(_fixture("sherlock_object_full")["crossmatches"]) == 4
    assert len(_fixture("sherlock_objects_full")["crossmatches"]) == 4



def test_live_object_and_plural_object_are_fully_accounted() -> None:
    obj = _fixture("object_default")
    objs = _fixture("objects_plural")
    _assert_zero_unaccounted("object", "object_default")
    _assert_zero_unaccounted("objects", "objects_plural")
    assert len(obj["candidates"]) == 92
    portfolio = _build("object", obj)
    summary = next(r for r in portfolio.records if r.semantic_type == "summary@ztf:lasair")
    assert summary.fields["detection_count"] == 35
    assert summary.fields["time.first_detection"] == "2020-11-12 10:27:04"
    tns = next(r for r in portfolio.records if r.semantic_type == "crossmatch@tns:lasair")
    assert tns.fields["separation.total"] == pytest.approx(0.12)
    assert tns.fields["photometry.r.mag"] == pytest.approx(19.7399)
    plural = _build("objects", objs)
    assert len([r for r in plural.records if r.semantic_type == "detection@ztf:lasair"]) == 92


def test_plural_objects_keep_nested_candidates_with_their_root() -> None:
    first = _fixture("objects_plural")[0]
    second = copy.deepcopy(first)
    second["objectId"] = "ZTF-synthetic-second-root"
    second["candidates"] = second["candidates"][:7]

    portfolios = _build_all("objects", [first, second])
    assert len(portfolios) == 2
    by_object_id = {
        next(
            record.fields["identity.object_id"]
            for record in portfolio.records
            if record.semantic_type == "summary@ztf:lasair"
        ): portfolio
        for portfolio in portfolios
    }
    assert set(by_object_id) == {first["objectId"], second["objectId"]}
    assert {
        object_id: len([
            record for record in portfolio.records
            if record.semantic_type == "detection@ztf:lasair"
        ])
        for object_id, portfolio in by_object_id.items()
    } == {first["objectId"]: len(first["candidates"]), second["objectId"]: 7}
    assert all(
        portfolio.executions[0].internal_execution_id
        == InternalExecutionId("execution:fixture:objects")
        for portfolio in portfolios
    )
    assert len({portfolio.internal_portfolio_id for portfolio in portfolios}) == 2

def test_live_lightcurve_is_fully_accounted_with_detections_and_limits() -> None:
    payload = _fixture("lightcurves")
    rows = payload[0]["candidates"]
    assert len(rows) == 92
    assert sum("candid" in row for row in rows) == 35
    assert sum("diffmaglim" in row for row in rows) == 57
    _assert_zero_unaccounted("lightcurves", "lightcurves")

    portfolio = _build("lightcurves", payload)
    detections = [
        record for record in portfolio.records
        if record.semantic_type == "detection@ztf:lasair"
    ]
    measured = next(
        record for record in detections
        if record.fields.get("identity.source_id") == 1411435461415015019
    )
    measured_fields = dict(measured.fields)
    assert measured_fields["identity.night_id"] == 1411
    assert measured_fields["photometry.r.psf.mag"] == 19.739900588989258
    assert "solar_system.mpc_match.identity.object_id" not in measured_fields
    assert "solar_system.mpc_match.separation.total" not in measured_fields

    upper = next(
        record for record in detections
        if record.fields.get("photometry.g.limit.mag") == 19.93899917602539
    )
    upper_fields = dict(upper.fields)
    assert "photometry.g.upper_limit" not in upper_fields
    assert "photometry.g.psf.mag" not in upper_fields


def test_live_fixed_query_projection_is_fully_accounted() -> None:
    payload = _fixture("query_core")
    assert payload == [{
        "objectId": "ZTF20acpwljl",
        "ramean": 124.87996115142856,
        "decmean": -6.0205001000000005,
        "ncand": 35,
        "jdmin": 2459165.935463,
        "jdmax": 2459194.9610532,
    }]
    _assert_zero_unaccounted("query", "query_core")

    portfolio = _build("query", payload)
    summary = next(
        record for record in portfolio.records
        if record.semantic_type == "summary@ztf:lasair"
    )
    fields = dict(summary.fields)
    assert fields["identity.object_id"] == "ZTF20acpwljl"
    assert fields["detection_count"] == 35
    assert fields["time.first_mjd"] == pytest.approx(59165.43546300009)
    assert fields["time.last_mjd"] == pytest.approx(59194.461053200066)


def test_live_plural_sherlock_object_shape_is_fully_accounted() -> None:
    payload = _fixture("sherlock_objects_full")
    assert isinstance(payload, dict)
    assert len(payload["crossmatches"]) == 4
    _assert_zero_unaccounted("sherlock_objects", "sherlock_objects_full")

    portfolio = _build("sherlock_objects", payload)
    semantic_types = {record.semantic_type for record in portfolio.records}
    assert "classification@sherlock:lasair" in semantic_types
    assert "crossmatch@sdss_2mass_ps1:lasair" in semantic_types
    assert "crossmatch@twomass:lasair" in semantic_types
    assert "crossmatch@panstarrs:lasair" in semantic_types
    assert "crossmatch@sdss:lasair" in semantic_types


@pytest.mark.parametrize(
    ("endpoint", "name"),
    [("sherlock_object", "sherlock_object_lite"),
     ("sherlock_object", "sherlock_object_full"),
     ("sherlock_objects", "sherlock_objects_lite"),
     ("sherlock_objects", "sherlock_objects_full")],
)
def test_authoritative_object_sherlock_capture_remains_one_portfolio(endpoint, name):
    _assert_zero_unaccounted(endpoint, name)
    payload = _fixture(name)
    (portfolio,) = _build_all(endpoint, payload)
    assert set(payload["classifications"]) == {"ZTF20acpwljl"}
    assert {row["transient_object_id"] for row in payload["crossmatches"]} == {
        "ZTF20acpwljl"
    }
    assert {r.internal_source.payload_key.rsplit("_", 1)[-1]
            for r in portfolio.records if r.internal_source is not None} >= {
                "classifications", "crossmatches"
            }


@pytest.mark.parametrize(
    ("endpoint", "name"),
    [("sherlock_position", "sherlock_position_lite"),
     ("sherlock_object", "sherlock_object_lite"),
     ("sherlock_objects", "sherlock_objects_lite")],
)
def test_authoritative_lite_sherlock_photometry_is_accounted(endpoint, name):
    _assert_zero_unaccounted(endpoint, name)
    (portfolio,) = _build_all(endpoint, _fixture(name))
    crossmatch = next(
        record for record in portfolio.records
        if record.semantic_type.startswith("crossmatch@")
        and "photometry.r.mag" in record.fields
    )
    assert crossmatch.fields["photometry.r.mag"] == pytest.approx(19.142)
    assert crossmatch.fields["photometry.r.mag.error"] == pytest.approx(0.002)
    assert all("{filter}" not in field for field in crossmatch.fields)
