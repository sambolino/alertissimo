from alertissimo.app_plot import (
    DEFAULT_DATA_PATH,
    SEMANTIC_RECORD_FAMILIES,
    load_lightcurve_json,
    semantic_record_index,
    selected_chart_point,
    lightcurve_chart,
    lightcurve_dataframe,
)


def test_demo_portfolio_adapter_exposes_ontology_record_families():
    records = semantic_record_index(load_lightcurve_json(DEFAULT_DATA_PATH))

    families = {record["family"] for record in records}
    assert families <= set(SEMANTIC_RECORD_FAMILIES)
    assert {
        "summary", "detection", "crossmatch", "lightcurve", "data_product",
        "classification", "survey",
    } <= families
    assert all(record["semantic_type"].endswith("@demo:local") for record in records)


def test_demo_detection_records_are_concrete_and_lightcurve_is_grouped():
    data = load_lightcurve_json(DEFAULT_DATA_PATH)
    records = semantic_record_index(data)

    detections = [record for record in records if record["family"] == "detection"]
    lightcurves = [record for record in records if record["family"] == "lightcurve"]
    assert len(detections) == len(data["lightCurve"])
    assert len(lightcurves) == 1
    assert lightcurves[0]["fields"]["point_count"] == len(detections)


def test_chart_selection_extracts_the_selected_detection_identifier():
    event = {"selection": {"detection_point_test": [{"_point_id": "4"}]}}

    assert selected_chart_point(event, "detection_point_test") == "4"
    assert selected_chart_point({"selection": {}}, "detection_point_test") is None


def test_clickable_lightcurve_is_a_single_view_chart_for_streamlit_selection():
    frame, _ = lightcurve_dataframe(load_lightcurve_json(DEFAULT_DATA_PATH))
    frame = frame.assign(_point_id=frame.index.astype(str))

    spec = lightcurve_chart(frame, selection_name="detection_point_test").to_dict()
    assert "layer" not in spec
    assert "detection_point_test" in spec["params"][0]["name"]
