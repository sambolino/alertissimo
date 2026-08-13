"""Regression tests against the frozen authenticated Lasair/ZTF capture."""

from __future__ import annotations

from itertools import count
import json
from pathlib import Path

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
    InternalPortfolioId,
    InternalRecordId,
)
from alertissimo.data_layer.runtime.record_builder import build_portfolio_from_execution
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
    assert upper_fields["photometry.g.limit.upper_limit"] is True
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
    assert fields["time.first_mjd"] == 59165.43546299962
    assert fields["time.last_mjd"] == 59194.4610531996


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
