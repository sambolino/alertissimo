from alertissimo.app_plot import (
    SEMANTIC_RECORD_FAMILIES,
    arrow_safe_dataframe,
    load_lightcurve_document,
    semantic_record_index,
    selected_chart_point,
    lightcurve_chart,
    lightcurve_dataframe,
)
from alertissimo.ui_portfolios import DEFAULT_PORTFOLIO, load_ui_portfolio


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
