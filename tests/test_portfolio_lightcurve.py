from __future__ import annotations

import math

import pandas as pd
import pytest

from alertissimo.data_layer.presentation.portfolio_lightcurve import (
    LIGHTCURVE_COLUMNS,
    portfolio_lightcurve_dataframe,
    select_mjd,
    serialized_portfolio_lightcurve_dataframe,
)
from alertissimo.data_layer.representations import (
    InternalPortfolioId,
    InternalRecordId,
    Portfolio,
    SemanticRecord,
)
from alertissimo.data_layer.runtime.serialization import portfolio_to_dict


def record(record_id: str, fields: dict, semantic_type: str = "detection@ztf:fink") -> SemanticRecord:
    return SemanticRecord(InternalRecordId(record_id), semantic_type, fields)


def portfolio(*records: SemanticRecord) -> Portfolio:
    return Portfolio(InternalPortfolioId("portfolio-test"), records=records)


def test_projects_magnitude_and_pairs_its_error():
    frame = portfolio_lightcurve_dataframe(portfolio(record("r1", {
        "time.mjd": 60001.25,
        "photometry.g.psf.mag": 19.4,
        "photometry.g.psf.mag.error": 0.12,
    })))

    assert list(frame.columns) == LIGHTCURVE_COLUMNS
    assert frame.to_dict("records") == [{
        "record_id": "r1",
        "semantic_type": "detection@ztf:fink",
        "mjd": 60001.25,
        "band": "g",
        "measurement_kind": "ordinary",
        "quantity": "mag",
        "value": 19.4,
        "error": 0.12,
    }]


def test_projects_flux_multiple_filters_and_missing_error():
    frame = portfolio_lightcurve_dataframe(portfolio(record("r1", {
        "time.mjd": 60002,
        "photometry.g.psf.flux": 1200,
        "photometry.g.psf.flux.error": 30,
        "photometry.r.psf.flux": 900,
    })))

    assert list(frame["band"]) == ["g", "r"]
    assert set(frame["quantity"]) == {"flux"}
    assert frame.loc[0, "error"] == 30
    assert math.isnan(frame.loc[1, "error"])


def test_forced_photometry_is_distinguished_with_or_without_psf_segment():
    frame = portfolio_lightcurve_dataframe(portfolio(record("r1", {
        "time.mjd": 60003,
        "forced_photometry.i.psf.flux": 10,
        "forced_photometry.i.psf.flux.error": 2,
        "forced_photometry.z.mag": 21,
    })))

    assert set(frame["measurement_kind"]) == {"forced"}
    assert set(zip(frame["band"], frame["quantity"])) == {("i", "flux"), ("z", "mag")}


def test_null_missing_nonfinite_values_and_time_are_ignored():
    result = portfolio_lightcurve_dataframe(portfolio(
        record("null", {"time.mjd": 1, "photometry.g.psf.mag": None}),
        record("missing-time", {"photometry.g.psf.mag": 20}),
        record("nan", {"time.mjd": 2, "photometry.g.psf.mag": float("nan")}),
        record("valid", {"time.mjd": 3, "photometry.g.psf.mag": 19}),
    ))

    assert list(result["record_id"]) == ["valid"]


def test_unrelated_semantic_records_and_photometry_paths_are_ignored():
    frame = portfolio_lightcurve_dataframe(portfolio(
        record("summary", {"time.mjd": 1, "photometry.g.psf.mag": 10}, "summary@ztf:fink"),
        record("crossmatch", {"time.mjd": 1, "photometry.g.psf.mag": 11}, "crossmatch@gaia:fink"),
        record("detection", {
            "time.mjd": 1,
            "reference_image.photometry.g.psf.mag": 12,
            "photometry.g.aperture.mag": 13,
        }),
    ))

    assert frame.empty
    assert list(frame.columns) == LIGHTCURVE_COLUMNS


@pytest.mark.parametrize("semantic_type", [
    "detection",
    "detection@ztf",
    "detection@ztf:fink",
    "detection@lsst:alerce",
])
def test_producer_and_broker_qualification_do_not_affect_extraction(semantic_type):
    frame = portfolio_lightcurve_dataframe(portfolio(record(
        semantic_type, {"time.mjd": 42, "photometry.r.psf.mag": 18}, semantic_type
    )))
    assert len(frame) == 1
    assert frame.iloc[0]["semantic_type"] == semantic_type


def test_time_selection_is_explicit_ordered_and_normalized():
    fields = {"time.processed_mjd": 999, "time.mjd": 5, "time.observed_mjd": 4}
    assert select_mjd(fields) == 5
    assert select_mjd(fields, ("time.observed_mjd", "time.mjd")) == 4
    assert select_mjd({"time.mjd": None}) is None


def test_stable_serialization_adapter_matches_primary_projection():
    value = portfolio(record("r1", {"time.mjd": 6, "photometry.g.psf.mag": 17}))
    expected = portfolio_lightcurve_dataframe(value)
    actual = serialized_portfolio_lightcurve_dataframe(portfolio_to_dict(value))
    pd.testing.assert_frame_equal(actual, expected)


def test_primary_api_rejects_serialized_dict():
    with pytest.raises(TypeError, match="in-memory Portfolio"):
        portfolio_lightcurve_dataframe({"records": []})  # type: ignore[arg-type]

def test_package_level_lightcurve_export_uses_lazy_public_api():
    from alertissimo.data_layer.presentation import (
        portfolio_lightcurve_dataframe as public_dataframe,
    )

    assert public_dataframe is portfolio_lightcurve_dataframe
