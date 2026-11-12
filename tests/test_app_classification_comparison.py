"""Classification comparison is a source-preserving view, not a classifier."""

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

import alertissimo.app_plot as app_plot
from alertissimo.app_plot import classification_table_rows, render_classification
from alertissimo.ui_portfolios import (
    classification_card_summary, classification_rows, load_ui_portfolio, portfolio_to_display,
)


def source(execution="fink", index=0):
    return {"internal_execution_id": f"execution:{execution}", "payload_key": "objects",
            "payload_path": f"$[{index}]", "payload_index": index}


def record(identifier, fields, semantic_type="classification@fink", *, internal_source=None):
    return {"internal_record_id": identifier, "semantic_type": semantic_type,
            "fields": fields, "internal_source": source() if internal_source is None else internal_source}


def portfolio(*records):
    return {
        "internal_portfolio_id": "portfolio:comparison", "edges": [],
        "records": [record("summary", {"identity.object_id": "ZTF-test", "time.last_mjd": 99999},
                           "summary@ztf:fink"), *records],
        "executions": [{"internal_execution_id": "execution:fink", "broker": "fink", "origin": "ztf",
                        "endpoint": "objects", "finished_at": "2026-11-05T01:00:00Z",
                        "adapter_version": "not-a-classifier-version"}],
    }


def test_each_output_keeps_its_own_label_probability_score_and_original_fields():
    raw = portfolio(record("classes", {
        "best.class": "preferred upstream label",
        "assessment.alpha.class": "AGN", "assessment.alpha.probability": 0.1,
        "assessment.beta.class": "SN", "assessment.beta.score": 2,
        "assessment.gamma.probability": 0.85, "assessment.gamma.rank": 0,
        "assessment.elephant.hostless_science_score": 0.7,
    }))
    snapshot = deepcopy(raw)
    display = portfolio_to_display(raw)
    rows = {row["output"]: row for row in display["classifications"]}
    assert rows["best"]["class"] == "preferred upstream label"
    assert rows["best"]["probability"] is None
    assert (rows["assessment.alpha"]["class"], rows["assessment.alpha"]["probability"]) == ("AGN", 0.1)
    assert (rows["assessment.beta"]["class"], rows["assessment.beta"]["score"]) == ("SN", 2)
    assert rows["assessment.beta"]["probability"] is None
    assert rows["assessment.gamma"]["class"] is None
    assert rows["assessment.gamma"]["probability"] == 0.85 and rows["assessment.gamma"]["rank"] == 0
    assert rows["assessment.elephant"]["other_values"] == {"hostless_science_score": 0.7}
    assert {row["broker"] for row in rows.values()} == {"fink"}
    assert {row["producer"] for row in rows.values()} == {"fink"}
    assert all(row["version"] is None for row in rows.values())
    assert raw == snapshot
    assert display["semantic_records"][1]["fields"] == snapshot["records"][1]["fields"]


@pytest.mark.parametrize("reverse", [False, True])
def test_versions_conflicts_and_duplicate_assertions_remain_visible_without_ranking(reverse):
    assertions = [record(f"version:{i}", {
        "provenance.producer.name": "model", "provenance.producer.version": version,
        "best.class": label, "best.probability": probability,
    }, "classification@model:fink") for i, (version, label, probability) in enumerate([
        ("v99", "SN", 0.99), ("v2", "AGN", 0.2), ("v2", "AGN", 0.2),
    ])]
    if reverse:
        assertions.reverse()
    display = portfolio_to_display(portfolio(*assertions))
    assert len(display["classifications"]) == 3
    assert {row["record_id"] for row in display["classifications"]} == {"version:0", "version:1", "version:2"}
    assert {row["version"] for row in display["classifications"]} == {"v99", "v2"}
    assert classification_card_summary(display) == ("2 labels", None)


def test_observation_assertion_production_and_retrieval_times_have_distinct_sources():
    raw = portfolio(
        record("observation", {"identity.source_id": 170666304474710039, "time.mjd": 60001}, "measurement@ztf:fink"),
        record("unrelated", {"identity.source_id": 2, "time.mjd": 60099}, "measurement@ztf:fink", internal_source=source(index=1)),
        record("classification", {"best.class": "SN", "provenance.time.mjd": 60123,
                                  "provenance.time.processed_mjd": 60124,
                                  "provenance.time.datetime": "2023-06-01T00:00:00Z"}),
    )
    row, = classification_rows(raw)
    assert row["observation_mjd"] == "60001"
    assert row["source_id"] == "170666304474710039"
    assert row["assertion_mjd"] == 60123
    assert row["produced_mjd"] == 60124
    assert row["assertion_datetime"] == "2023-06-01T00:00:00Z"
    assert row["retrieved_at"] == "2026-11-05T01:00:00Z"
    assert row["endpoint"] == "objects"
    assert row["version"] is None


def test_incomplete_source_and_object_summary_do_not_invent_an_observation_or_issue_time():
    incomplete = {"internal_execution_id": "execution:fink"}
    raw = portfolio(record("observation", {"time.mjd": 60001}, "measurement@ztf:fink", internal_source=incomplete),
                    record("classification", {"best.class": "SN"}, internal_source=incomplete))
    raw["executions"][0].pop("finished_at")
    raw["executions"][0]["started_at"] = "request-start-only"
    row, = classification_rows(raw)
    assert row["observation_mjd"] is None
    assert row["assertion_mjd"] is None and row["produced_mjd"] is None
    assert row["retrieved_at"] is None


def test_multiple_associated_epochs_are_shown_without_choosing_a_latest_one():
    row, = classification_rows(portfolio(
        record("observation:1", {"time.mjd": 60001}, "measurement@ztf:fink"),
        record("observation:2", {"time.mjd": 60002}, "measurement@ztf:fink"),
        record("class", {"best.class": "SN"}),
    ))
    assert row["observation_mjd"] == "60001 · 60002"


def test_missing_delivery_source_is_not_inferred_from_producer_name():
    raw = portfolio(record("class", {"best.class": "SN"}))
    raw["executions"] = []
    row, = classification_rows(raw)
    assert row["producer"] == "fink" and row["broker"] is None
    assert row["version"] is None and row["retrieved_at"] is None


@pytest.mark.parametrize("rows,expected", [
    ([], ("—", None)),
    ([{"class": "SN", "score": 2}], ("SN", None)),
    ([{"class": "SN", "probability": 0.83}], ("SN", 0.83)),
    ([{"class": "SN", "probability": True}], ("SN", None)),
    ([{"class": "SN", "probability": 2}], ("SN", None)),
    ([{"class": "SN", "probability": float("nan")}], ("SN", None)),
    ([{"class": "SN", "probability": 0.99}, {"class": "SN", "probability": 0.2}], ("SN", None)),
    ([{"class": "SN", "probability": 0.99}, {"class": "AGN", "probability": 0.2}], ("2 labels", None)),
])
def test_card_never_chooses_between_assertions_or_formats_a_score_as_probability(rows, expected):
    assert classification_card_summary({"classifications": rows}) == expected


def test_table_and_inspector_keep_score_scale_and_selected_record_provenance(monkeypatch):
    raw = portfolio(record("chosen", {"best.class": "SN", "best.score": 2}, "classification@sherlock:fink"))
    display = portfolio_to_display(raw)
    captured = {"tables": [], "json": [], "keys": []}

    class FakeStreamlit:
        column_config = app_plot.st.column_config

        def markdown(self, *_args):
            pass

        def caption(self, *_args):
            pass

        def dataframe(self, data, **kwargs):
            captured["tables"].append((data, kwargs))

        def selectbox(self, _label, options, **kwargs):
            captured["keys"].append(kwargs["key"])
            return options[0]

        def json(self, value, **_kwargs):
            captured["json"].append(value)

    monkeypatch.setattr(app_plot, "st", FakeStreamlit())
    render_classification(display, widget_key="object-one")
    frame, config = captured["tables"][0]
    assert frame.iloc[0]["Score"] == 2
    assert frame.iloc[0]["Probability"] is None
    assert config["column_config"]["Score"]["type_config"]["type"] == "number"
    assert captured["json"][0] == raw["records"][1]["fields"]
    assert captured["json"][1] == {"internal_source": raw["records"][1]["internal_source"],
                                    "execution": raw["executions"][0]}
    assert captured["keys"] == ["classification_inspector_object-one"]


def test_catalogue_context_is_not_relabelled_as_candidate_classification(monkeypatch):
    display = portfolio_to_display(portfolio(record("catalogue", {
        "classification.assessment.gaia_variability.class": "AGN",
    }, "crossmatch@gaia:antares")))
    messages = []
    fake = SimpleNamespace(markdown=lambda *_: None, info=messages.append)
    monkeypatch.setattr(app_plot, "st", fake)
    render_classification(display)
    assert messages == ["No classification evidence is available."]
    assert len(display["context"]["crossmatches"]) == 1


def test_frozen_brokers_preserve_model_versions_numeric_labels_and_reliability():
    alerce = classification_rows(load_ui_portfolio("ztf_alerce_ZTF18abbuksn.json"))
    assert any(r["output"] == "assessment.snia" and r["class"] == "SNIa"
               and r["rank"] == 11 and r["version"] == "hierarchical_rf_1.1.0" for r in alerce)
    assert len({r["version"] for r in alerce if r["version"] is not None}) > 1
    fink = classification_rows(load_ui_portfolio("lsst_fink_170587117485817955.json"))
    cats = [r for r in fink if r["output"] == "assessment.cats"]
    assert cats and any(r["class"] == 11 and r["score"] == 0.998451 for r in cats)
    assert all(r["probability"] is None and r["observation_mjd"] is not None for r in cats)
    lasair = classification_rows(load_ui_portfolio("ztf_lasair_ZTF20acpwljl.json"))
    assert any(r["producer"] == "sherlock" and r["class"] == "SN"
               and r["score"] == 2 and r["probability"] is None for r in lasair)


def test_classification_view_is_available_without_photometry_and_with_distinct_widget_keys():
    raw = portfolio(record("class", {"best.class": "SN", "best.score": 2}))
    script = ("import json\nfrom alertissimo.app_plot import load_lightcurve_document, render_object_portfolio\n"
              f"data = load_lightcurve_document(json.loads({json.dumps(raw)!r}))\n"
              "render_object_portfolio(data, widget_key='one')\n"
              "render_object_portfolio(data, widget_key='two')\n")
    app = AppTest.from_string(script).run(timeout=30)
    assert not app.exception
    assert [tab.label for tab in app.tabs].count("Classifications") == 2
    inspectors = [box for box in app.selectbox if box.label == "Inspect classification record"]
    assert {box.key for box in inspectors} == {"classification_inspector_one", "classification_inspector_two"}
    assert any("Score" in table.value.columns and table.value.iloc[0]["Score"] == 2 for table in app.dataframe)


def test_frozen_multibroker_table_renders_and_its_source_record_can_be_selected():
    name = "multibroker_lsst_170587117485817955.json"
    script = ("from alertissimo.app_plot import render_classification\n"
              "from alertissimo.ui_portfolios import load_ui_portfolio, portfolio_to_display\n"
              f"render_classification(portfolio_to_display(load_ui_portfolio({name!r})))\n")
    app = AppTest.from_string(script).run(timeout=30)
    assert not app.exception
    frame = app.dataframe[0].value
    assert set(frame["Broker"]) == {"alerce", "fink"}
    assert {"Probability", "Score", "Rank", "Version", "Source ID"} <= set(frame.columns)
    rows = classification_rows(load_ui_portfolio(name))
    selected = next(row["record_id"] for row in rows if row["output"] == "assessment.cats")
    app.selectbox[0].set_value(selected).run(timeout=30)
    assert not app.exception
    assert app.selectbox[0].value == selected


def test_stored_headline_projection_exposes_scope_policy_and_visible_errors():
    raw = portfolio(record("native", {"best.class": "Future label"}), record("headline", {
        "best.native_class": "Future label", "best.status": "error",
        "best.error_code": "unmapped_label", "best.broker": "fink", "best.survey": "ztf",
        "best.policy": "fink-ztf-headline-v1", "best.mapping_version": "coarse-v1",
        "best.policy_digest": "pinned-hash", "best.source_method": "fink",
        "best.selected_record_ids": ["native"],
    }, "classification@headline:fink", internal_source={}))
    snapshot = deepcopy(raw)
    display = portfolio_to_display(raw)
    rows = classification_table_rows(display)
    assert len(rows) == 2
    assert rows[1]["Normalization error"] == "unmapped_label"
    assert rows[1]["Policy digest"] == "pinned-hash"
    assert rows[1]["Selected native records"] == ["native"]
    assert raw == snapshot
    def app():
        import streamlit as st
        from alertissimo.app_plot import render_classification
        render_classification(st.session_state["data"])
    at = AppTest.from_function(app)
    at.session_state["data"] = display
    at.run()
    assert not at.exception
    assert "unmapped_label" in at.error[0].value


def test_headline_cards_do_not_use_an_alternative_probability():
    display = {"classifications": [
        {"class": "AGN", "probability": 0.99},
        {"headline": True, "class": "SNIa", "probability": 0.1},
    ]}
    assert classification_card_summary(display) == ("SNIa", 0.1)
    display["classifications"].append({"headline": True, "class": "SN", "probability": 0.9})
    assert classification_card_summary(display) == ("2 labels", None)
