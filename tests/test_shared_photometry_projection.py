"""Both UI adapters consume the same scientific rows without editing records."""
from copy import deepcopy
import json

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from alertissimo.app_plot import lightcurve_chart, lightcurve_dataframe
from alertissimo.data_layer.presentation.portfolio_lightcurve import serialized_portfolio_lightcurve_dataframe
from alertissimo.ui.app import lightcurve_chart as upload_chart
from alertissimo.ui_portfolios import latest_magnitude, portfolio_to_display


def evidence():
    return {"internal_portfolio_id": "test", "edges": [], "executions": [], "records": [
        {"internal_record_id": "summary", "semantic_type": "summary@ztf:fink", "fields": {
            "identity.object_id": "ZTF-test", "position.ra": 0.0, "position.dec": 0.0}},
        {"internal_record_id": "mixed", "semantic_type": "measurement@ztf:fink", "fields": {
            "time.mjd": 60000, "photometry.g.psf.mag": 20.0,
            "photometry.r.psf.mag": 19.0, "photometry.r.psf.mag.error": 0.2,
            "photometry.g.psf.flux": -3.0, "forced_photometry.i.psf.flux": 4.0,
            "forced_photometry.i.psf.flux.error": 1.0,
            "forced_photometry.z.mag": 21.0, "photometry.y.limit.mag": 25.0}},
    ]}


def test_all_quantities_bands_kinds_and_limits_reach_both_views_unchanged():
    raw = evidence()
    before = deepcopy(raw)
    generic = serialized_portfolio_lightcurve_dataframe(raw)
    display = portfolio_to_display(raw)
    frame, rejected = lightcurve_dataframe(display)
    columns = ["record_id", "semantic_type", "mjd", "band", "measurement_kind", "quantity", "value", "error", "is_upper_limit"]
    pd.testing.assert_frame_equal(frame[columns].reset_index(drop=True), generic, check_dtype=False)
    assert len(frame) == 6 and rejected == 0
    assert sorted(frame.loc[frame["quantity"] == "flux", "value"].tolist()) == [-3.0, 4.0]
    assert frame["is_upper_limit"].sum() == 1
    assert display["coordinates"] == {"ra": 0.0, "dec": 0.0}
    assert raw == before
    assert display["semantic_records"][1]["fields"] == before["records"][1]["fields"]


def test_absent_uncertainty_stays_unknown_and_latest_mag_excludes_limits_and_flux():
    display = portfolio_to_display(evidence())
    ordinary = next(p for p in display["lightCurve"] if p["band"] == "g" and p["quantity"] == "mag" and not p["is_upper_limit"])
    assert ordinary["error"] is None and ordinary["magnitudeError"] is None
    assert latest_magnitude({"lightCurve": [ordinary, {"magnitude": 25.0, "is_upper_limit": True}, {"magnitude": None, "quantity": "flux"}]}) == 20.0
    assert latest_magnitude({"lightCurve": [{"magnitude": None, "quantity": "flux"}]}) is None


def test_exposure_limiting_depth_does_not_manufacture_a_non_detection():
    raw = evidence()
    raw["records"][1]["fields"] = {
        "time.mjd": 60000, "photometry.g.psf.mag": 19.0, "photometry.g.limit.mag": 22.0,
    }
    frame = serialized_portfolio_lightcurve_dataframe(raw)
    assert frame["value"].tolist() == [19.0]
    assert not frame["is_upper_limit"].any()
    assert portfolio_to_display(raw)["semantic_records"][1]["fields"]["photometry.g.limit.mag"] == 22.0


@pytest.mark.parametrize("quantity,reverse", [("mag", True), ("flux", False)])
def test_both_charts_keep_quantity_direction_and_limit_marker(quantity, reverse):
    raw = evidence()
    generic = serialized_portfolio_lightcurve_dataframe(raw)
    frame, _ = lightcurve_dataframe(portfolio_to_display(raw))
    spec = lightcurve_chart(frame[frame["quantity"] == quantity], selection_name="chosen").to_dict()
    upload = upload_chart(generic[generic["quantity"] == quantity]).to_dict()
    assert spec["encoding"]["y"]["scale"]["reverse"] is reverse
    assert upload["layer"][1]["encoding"]["y"]["scale"]["reverse"] is reverse
    assert spec["encoding"]["shape"]["scale"]["range"] == ["circle", "square", "triangle-down"]
    assert spec["encoding"]["y"]["field"] == "value"


@pytest.mark.parametrize("path,quantity", [("forced_photometry.g.psf.flux", "flux"), ("photometry.r.limit.mag", "mag")])
def test_investigation_renders_forced_only_and_limit_only_evidence(path, quantity):
    raw = evidence()
    raw["records"][1]["fields"] = {"time.mjd": 60000, path: 20.0}
    script = ("import json\nfrom alertissimo.app_plot import load_lightcurve_document, render_object_portfolio\n"
              f"render_object_portfolio(load_lightcurve_document(json.loads({json.dumps(raw)!r})))\n")
    app = AppTest.from_string(script).run(timeout=30)
    assert not app.exception
    assert "Detections & light curve" in [tab.label for tab in app.tabs]
    assert next(s.value for s in app.selectbox if s.label == "Quantity") == quantity
    assert not any("no loaded" in item.value.lower() for item in app.info)
