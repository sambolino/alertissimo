import alertissimo.app_plot as app_plot

from alertissimo.app_plot import (
    SEMANTIC_RECORD_FAMILIES,
    arrow_safe_dataframe,
    load_lightcurve_document,
    semantic_record_index,
    selected_chart_point,
    lightcurve_chart,
    lightcurve_dataframe,
)
from alertissimo.ui_portfolios import DEFAULT_PORTFOLIO, load_ui_portfolio, loaded_photometry_counts, portfolio_to_display


def portfolio_data():
    return load_lightcurve_document(load_ui_portfolio(DEFAULT_PORTFOLIO))


def test_portfolio_adapter_exposes_ontology_record_families():
    records = semantic_record_index(portfolio_data())

    families = {record["family"] for record in records}
    assert families <= set(SEMANTIC_RECORD_FAMILIES)
    assert {
        "summary", "detection", "crossmatch", "lightcurve", "classification",
    } <= families
    assert all("@" in record["semantic_type"] for record in records)


def test_detection_records_are_concrete_and_lightcurve_is_grouped():
    data = portfolio_data()
    records = semantic_record_index(data)

    detections = [record for record in records if record["family"] == "detection"]
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


def detection_evidence_portfolio():
    return {
        "records": [
            {
                "internal_record_id": f"record:{broker}",
                "semantic_type": f"detection@ztf:{broker}",
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
    assert points["fink"]["semantic_type"] == "detection@ztf:fink"
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
