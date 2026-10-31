import alertissimo.app_plot as app_plot
from contextlib import nullcontext
from copy import deepcopy

import pandas as pd
import pytest

from alertissimo.app_plot import (
    SEMANTIC_RECORD_FAMILIES,
    arrow_safe_dataframe,
    load_lightcurve_document,
    semantic_record_index,
    selected_chart_point,
    lightcurve_chart,
    lightcurve_dataframe,
    filter_photometry_frame,
)
from alertissimo.ui_portfolios import DEFAULT_PORTFOLIO, load_ui_portfolio, loaded_photometry_counts, portfolio_to_display


def portfolio_data():
    return load_lightcurve_document(load_ui_portfolio(DEFAULT_PORTFOLIO))


def test_portfolio_adapter_exposes_ontology_record_families():
    records = semantic_record_index(portfolio_data())

    families = {record["family"] for record in records}
    assert families <= set(SEMANTIC_RECORD_FAMILIES)
    assert {
        "summary", "measurement", "crossmatch", "lightcurve", "classification",
    } <= families
    assert all("@" in record["semantic_type"] for record in records)


def test_detection_records_are_concrete_and_lightcurve_is_grouped():
    data = portfolio_data()
    records = semantic_record_index(data)

    detections = [record for record in records if record["family"] == "measurement"]
    lightcurves = [record for record in records if record["family"] == "lightcurve"]
    assert len(detections) >= len(data["lightCurve"])
    assert lightcurves


def test_arrow_safe_dataframe_serializes_mixed_canonical_fields():
    frame = arrow_safe_dataframe([
        {"identity.object_id": 170587117485817955, "catalogs": ["gaia"]},
        {"identity.object_id": "ZTF20aafqubg", "catalogs": {"allwise": 1}},
    ])

    assert frame["identity.object_id"].tolist() == ["170587117485817955", "ZTF20aafqubg"]
    assert frame["catalogs"].tolist() == ['["gaia"]', '{"allwise": 1}']


def test_chart_selection_extracts_the_selected_detection_identifier():
    event = {"selection": {"detection_point_test": [{"_point_id": "4"}]}}

    assert selected_chart_point(event, "detection_point_test") == "4"
    assert selected_chart_point({"selection": {}}, "detection_point_test") is None


def test_clickable_lightcurve_is_a_single_view_chart_for_streamlit_selection():
    frame, _ = lightcurve_dataframe(portfolio_data())
    frame = frame.assign(_point_id=frame.index.astype(str))

    spec = lightcurve_chart(frame, selection_name="detection_point_test").to_dict()
    assert "layer" not in spec
    assert "detection_point_test" in spec["params"][0]["name"]
    assert next(item for item in spec["encoding"]["tooltip"] if item["field"] == "real_bogus")["format"] == ".6f"


def detection_evidence_portfolio():
    return {
        "records": [
            {
                "internal_record_id": f"record:{broker}",
                "semantic_type": f"measurement@ztf:{broker}",
                "fields": {
                    "identity.object_id": "ZTF-test", "time.mjd": 60001,
                    "photometry.g.psf.mag": 20.1, "photometry.g.psf.mag.error": 0.1,
                    "position.ra": 123.0,
                    **({"quality.real_bogus": 0.0, "quality.deep_real_bogus": 0.91} if broker == "fink" else {}),
                },
                "internal_source": {
                    "internal_execution_id": f"execution:{broker}",
                    "payload_path": "$[1]", "payload_index": 1,
                },
            }
            for broker in ("lasair", "fink")
        ],
        "executions": [
            {"internal_execution_id": f"execution:{broker}", "broker": broker,
             "origin": "ztf", "endpoint": "objects" if broker == "fink" else "lightcurves"}
            for broker in ("lasair", "fink")
        ],
    }


def test_detection_projection_exposes_provider_quality_and_preserves_overlapping_evidence():
    portfolio = detection_evidence_portfolio()
    display = portfolio_to_display(portfolio)
    points = {point["broker"]: point for point in display["lightCurve"]}

    assert points["fink"]["real_bogus"] == 0.0
    assert points["lasair"]["real_bogus"] is None
    assert points["fink"]["endpoint"] == "objects"
    assert points["fink"]["semantic_type"] == "measurement@ztf:fink"
    assert loaded_photometry_counts(display) == (("fink", 1), ("lasair", 1))
    assert display["semantic_records"][1]["internal_source"] == portfolio["records"][1]["internal_source"]


def test_selected_detection_renders_its_full_fields_and_own_execution_provenance(monkeypatch):
    portfolio = detection_evidence_portfolio()
    display = portfolio_to_display(portfolio)
    display["coordinates"]["ra"] = 999.0
    frame, _ = lightcurve_dataframe(display)
    selected = frame[frame["record_id"] == "record:fink"].iloc[0]
    json_values = []
    captions = []

    class FakeStreamlit:
        def markdown(self, *_args, **_kwargs):
            pass

        def caption(self, value):
            captions.append(value)

        def json(self, value, **_kwargs):
            json_values.append(value)

    monkeypatch.setattr(app_plot, "st", FakeStreamlit())
    app_plot.render_detection_details(display, selected)

    assert json_values[0] == portfolio["records"][1]["fields"]
    assert json_values[1]["internal_source"] == portfolio["records"][1]["internal_source"]
    assert json_values[1]["execution"] == portfolio["executions"][1]
    assert any("Broker: fink" in caption for caption in captions)


@pytest.mark.parametrize("threshold,include_missing,expected", [
    (None, False, [10, 11, 12, 13, 14, 15]),
    (0.999, False, [11, 12]),
    (0.999, True, [11, 12, 13, 14]),
    (0.0, False, [10, 11, 12, 15]),
])
def test_display_quality_filter_preserves_identity_and_distinguishes_missing_from_zero(
    threshold, include_missing, expected,
):
    frame = pd.DataFrame({
        "band": ["g"] * 6,
        "broker": ["fink"] * 6,
        "real_bogus": [0.9989, 0.999, "0.9999", None, float("nan"), 0.0],
        "record_id": [f"record:{index}" for index in range(6)],
    }, index=range(10, 16))
    original = frame.copy(deep=True)
    shown = filter_photometry_frame(
        frame, bands=["g"], min_real_bogus=threshold, include_missing=include_missing,
    )
    assert shown.index.tolist() == expected
    assert shown["record_id"].tolist() == original.loc[expected, "record_id"].tolist()
    pd.testing.assert_frame_equal(frame, original)


def test_display_filters_combine_band_broker_and_quality_and_allow_empty_selection():
    frame = pd.DataFrame({
        "band": ["g", "r", "g", "g"], "broker": ["fink", "fink", "lasair", "fink"],
        "real_bogus": [0.999, 0.9999, 0.9999, 0.1],
    })
    assert filter_photometry_frame(
        frame, bands=["g"], brokers=["fink"], min_real_bogus=0.999,
    ).index.tolist() == [0]
    assert filter_photometry_frame(frame, bands=[]).empty
    assert filter_photometry_frame(frame, bands=["g"], brokers=[]).empty
    unscored = frame.drop(columns="real_bogus")
    assert filter_photometry_frame(unscored, bands=["g"], min_real_bogus=0.999).empty
    assert len(filter_photometry_frame(
        unscored, bands=["g"], min_real_bogus=0.999, include_missing=True,
    )) == 3


@pytest.mark.parametrize("enabled,include_missing,selected_bands,expected", [
    (False, False, ["g"], ["record:lasair", "record:fink", "record:below"]),
    (True, False, ["g"], ["record:fink"]),
    (True, True, ["g"], ["record:lasair", "record:fink"]),
    (True, False, [], []),
])
def test_photometry_controls_share_one_selection_with_chart_table_count_and_inspector(
    monkeypatch, enabled, include_missing, selected_bands, expected,
):
    portfolio = detection_evidence_portfolio()
    portfolio["records"][1]["fields"]["quality.real_bogus"] = 0.999
    below = deepcopy(portfolio["records"][1])
    below["internal_record_id"] = "record:below"
    below["fields"]["quality.real_bogus"] = 0.9989
    portfolio["records"].append(below)
    original = deepcopy(portfolio)
    display = portfolio_to_display(portfolio)
    frame, rejected = lightcurve_dataframe(display)
    captured = {"chart": [], "table": [], "inspector": [], "metrics": {}}

    class FakeStreamlit:
        def columns(self, layout, **_kwargs):
            if isinstance(layout, int):
                return [self] * layout
            return [nullcontext(self) for _ in layout]

        def markdown(self, *_args, **_kwargs):
            pass

        def caption(self, *_args, **_kwargs):
            pass

        def image(self, *_args, **_kwargs):
            pass

        def pills(self, *_args, **_kwargs):
            return selected_bands

        def multiselect(self, *_args, **kwargs):
            return kwargs["default"]

        def checkbox(self, label, **_kwargs):
            return include_missing if label.startswith("Also show") else enabled

        def number_input(self, *_args, **_kwargs):
            return 0.999

        def metric(self, label, value):
            captured["metrics"][label] = value

        def info(self, *_args, **_kwargs):
            pass

        def altair_chart(self, *_args, **_kwargs):
            return {}

        def expander(self, *_args, **_kwargs):
            return nullcontext()

        def selectbox(self, _label, options, **_kwargs):
            captured["inspector"] = list(options)
            return options[0]

    monkeypatch.setattr(app_plot, "st", FakeStreamlit())

    def chart(shown, *_args, **_kwargs):
        captured["chart"] = shown["record_id"].tolist()
        assert shown["_point_id"].tolist() == shown.index.astype(str).tolist()

    def table(_data, *, frame, **_kwargs):
        captured["table"] = frame["record_id"].tolist()

    monkeypatch.setattr(app_plot, "lightcurve_chart", chart)
    monkeypatch.setattr(app_plot, "render_lightcurve_table", table)
    monkeypatch.setattr(app_plot, "render_record_evidence", lambda *_args: None)
    app_plot.render_photometry(display, frame, rejected, "test")
    assert captured["chart"] == expected
    assert captured["table"] == expected
    assert captured["inspector"] == expected
    assert captured["metrics"]["Shown points"] == len(expected)
    assert len(display["semantic_records"]) == 3
    assert portfolio == original
