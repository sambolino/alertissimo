from pathlib import Path
from types import SimpleNamespace
from contextlib import nullcontext

import pytest
from streamlit.testing.v1 import AppTest

from alertissimo.app_search import (
    block_discovery_brokers,
    block_requirement_brokers,
    candidate_result_key,
    compile_dsl_cone_preview,
    cone_candidates,
    load_demo_candidate_portfolios,
    load_demo_search_data,
    load_frozen_cone_candidates,
    load_block_capability_graph,
    reported_detection_metric,
)
from alertissimo.app_plot import summary_table_rows
from alertissimo.dsl.blocks import BlockRequirement, render_block_dsl
from alertissimo.orchestration.ir import ConeSearchStep
from alertissimo.ui_portfolios import portfolio_to_display, records_by_family
import alertissimo.app_search as app_search


def serialized_summary_portfolio(*records):
    """Return the stable Portfolio shape used by the UI projection tests."""

    brokers = [record[0].split(":", 1)[1] for record in records]
    return {
        "internal_portfolio_id": "portfolio:test:summary-evidence",
        "records": [
            {
                "internal_record_id": f"record:test:{index}",
                "semantic_type": semantic_type,
                "fields": fields,
                "internal_source": {
                    "internal_execution_id": (
                        f"execution:test:{semantic_type.rsplit(':', 1)[1]}"
                    )
                },
            }
            for index, (semantic_type, fields) in enumerate(records)
        ],
        "edges": [],
        "executions": [
            {
                "internal_execution_id": f"execution:test:{broker}",
                "broker": broker,
                "origin": "ztf",
                "endpoint": "search",
                "status": "succeeded",
            }
            for broker in brokers
        ],
    }


def test_provider_summaries_are_read_directly_without_new_ui_records():
    display = portfolio_to_display(
        serialized_summary_portfolio(
            (
                "summary@ztf:alerce",
                {
                    "identity.object_id": "ZTF-test",
                    "position.ra": 305.1,
                    "position.dec": 58.1,
                    "detection_count": 1044,
                    "time.first_mjd": 58001.0,
                    "time.last_mjd": 61001.0,
                },
            ),
            (
                "summary@ztf:fink",
                {
                    "identity.object_id": "ZTF-test",
                    "position.ra": 305.2,
                    "position.dec": 58.2,
                    "detection_count": 1037,
                    "time.first_mjd": 58002.0,
                    "time.last_mjd": 61002.0,
                },
            ),
        )
    )

    assert "summaryEvidence" not in display
    assert len(records_by_family(display, "summary")) == 2
    assert reported_detection_metric(display) == "alerce: 1044 · fink: 1037"
    assert summary_table_rows(display) == [
        {
            "Provider": "alerce",
            "Survey": "ztf",
            "Object ID": "ZTF-test",
            "RA": 305.1,
            "Dec": 58.1,
            "Reported detections": 1044,
            "First MJD": 58001.0,
            "Last MJD": 61001.0,
        },
        {
            "Provider": "fink",
            "Survey": "ztf",
            "Object ID": "ZTF-test",
            "RA": 305.2,
            "Dec": 58.2,
            "Reported detections": 1037,
            "First MJD": 58002.0,
            "Last MJD": 61002.0,
        },
    ]


def test_missing_reported_detection_count_is_not_rendered_as_zero():
    display = portfolio_to_display(
        serialized_summary_portfolio(
            (
                "summary@ztf:antares",
                {"identity.object_id": "ZTF-test", "position.ra": 1, "position.dec": 2},
            )
        )
    )

    assert reported_detection_metric(display) == "—"
    assert summary_table_rows(display)[0]["Reported detections"] == "—"


def test_live_result_card_leads_with_reported_not_loaded_detections(monkeypatch):
    display = portfolio_to_display(
        serialized_summary_portfolio(
            ("summary@ztf:lasair", {"identity.object_id": "ZTF-test"})
        )
    )

    class Column:
        def __init__(self, owner):
            self.owner = owner

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def metric(self, label, value, *args, **kwargs):
            self.owner.metrics.append((label, value))

    class FakeStreamlit:
        def __init__(self):
            self.metrics = []

        def columns(self, spec, **_kwargs):
            count = spec if isinstance(spec, int) else len(spec)
            return [Column(self) for _ in range(count)]

        def subheader(self, *_args, **_kwargs):
            pass

        def success(self, *_args, **_kwargs):
            pass

        def divider(self, *_args, **_kwargs):
            pass

        def markdown(self, *_args, **_kwargs):
            pass

        def caption(self, *_args, **_kwargs):
            pass

        def button(self, *_args, **_kwargs):
            return False

    fake_streamlit = FakeStreamlit()
    monkeypatch.setattr(app_search, "st", fake_streamlit)

    app_search.render_live_portfolio_cards([display], selection_state_key="selected")

    assert fake_streamlit.metrics[0] == ("Reported detections", "—")
    assert all(label != "Loaded points" for label, _value in fake_streamlit.metrics)


def test_conflicting_summary_identities_are_rejected_instead_of_selecting_first():
    portfolio = serialized_summary_portfolio(
        ("summary@ztf:alerce", {"identity.object_id": "ZTF-one"}),
        ("summary@ztf:fink", {"identity.object_id": "ZTF-two"}),
    )

    with pytest.raises(ValueError, match="conflicting summary object identities"):
        portfolio_to_display(portfolio)


def test_every_demo_search_result_has_a_distinct_portfolio_fixture():
    candidates, _ = load_demo_search_data()
    portfolios = load_demo_candidate_portfolios()

    object_ids = {candidate["object_id"] for candidate in candidates}
    assert object_ids <= portfolios.keys()
    assert {portfolio["diaObjectId"] for portfolio in portfolios.values()} == object_ids
    assert all(portfolio["semantic_records"] for portfolio in portfolios.values())
    assert all(portfolio["provenance"] for portfolio in portfolios.values())
    assert all(portfolio["lightCurve"] for portfolio in portfolios.values())


def test_frozen_cone_fixture_returns_all_captured_loci():
    candidates, preset = load_frozen_cone_candidates()

    matches = cone_candidates(candidates, **preset)
    assert len(matches) == 4
    assert {candidate["candidate_id"] for candidate in matches} == {
        "ANT2020nb5h6", "ANT2019afwxm", "ANT2020vzg6s", "ANT2020zt2xm"
    }
    assert {candidate_result_key(candidate) for candidate in matches} == {
        "ANT2020nb5h6", "ANT2019afwxm", "ANT2020vzg6s", "ANT2020zt2xm"
    }


def test_dsl_cone_preview_uses_the_existing_dsl_compiler():
    step = compile_dsl_cone_preview(
        "objects from ztf via antares\ninside (34, 33, 0.5deg)\n"
    )

    assert isinstance(step, ConeSearchStep)
    assert (step.ra, step.dec, step.radius) == (34.0, 33.0, 1800.0)


def test_dsl_without_cone_selector_has_no_local_results_preview():
    step = compile_dsl_cone_preview("objects from ztf via antares\nlatest 10\n")

    assert step is None


def test_block_builder_generates_parser_ready_dsl_without_clause_indentation():
    script = render_block_dsl(
        origins=("lsst", "ztf"),
        broker="alerce",
        ra_deg=150.124522,
        dec_deg=0.877582,
        radius=300,
        radius_unit="arcsec",
        latest=10,
        requirements=(BlockRequirement(product="lightcurve", broker="fink"),),
    )

    assert script == (
        "objects from lsst, ztf via alerce\n"
        "inside (150.12452, 0.87758, 300arcsec)\n"
        "latest 10\n"
        "with lightcurve via fink\n"
    )
    assert compile_dsl_cone_preview(script) is not None


def test_block_builder_options_are_capability_supported():
    graph = load_block_capability_graph()
    discovery_brokers = block_discovery_brokers(graph, ("ztf",))

    assert discovery_brokers
    for broker in discovery_brokers:
        assert block_requirement_brokers(
            graph,
            origins=("ztf",),
            discovery_broker=broker,
            product="lightcurve",
        )


def test_dsl_entry_uses_only_the_block_editor():
    app = AppTest.from_file(
        str(Path(__file__).parents[1] / "alertissimo" / "app_search.py")
    ).run(timeout=30)

    app.radio[0].set_value("DSL").run(timeout=30)

    assert not app.tabs
    assert not app.text_area
    assert not app.exception


def test_filter_dsl_entry_continues_from_the_visible_live_result(monkeypatch):
    """The nested filter editor must extend, rather than restart, its parent run."""

    class FakeStreamlit:
        session_state: dict[str, object] = {}

        def subheader(self, *_args, **_kwargs):
            pass

        def write(self, *_args, **_kwargs):
            pass

        def caption(self, *_args, **_kwargs):
            pass

        def success(self, *_args, **_kwargs):
            pass

        def spinner(self, *_args, **_kwargs):
            return nullcontext()

        def divider(self):
            pass

    previous_result = SimpleNamespace(portfolios=(object(),))
    calls = []
    nested = []
    editor_modes = []
    original_render = app_search.render_dsl_entry

    monkeypatch.setattr(app_search, "st", FakeStreamlit())
    def filter_editor(*, key, filter_only=False):
        editor_modes.append((key, filter_only))
        return "filter classification.best.probability >= 0.8", True

    monkeypatch.setattr(app_search, "render_dsl_block_input", filter_editor)
    monkeypatch.setattr(
        app_search,
        "execute_dsl",
        lambda source, **kwargs: calls.append((source, kwargs)) or previous_result,
    )
    monkeypatch.setattr(app_search, "portfolio_to_dict", lambda _portfolio: {})
    monkeypatch.setattr(app_search, "load_lightcurve_document", lambda _payload: {})
    monkeypatch.setattr(app_search, "render_live_portfolio_cards", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        app_search,
        "render_dsl_entry",
        lambda *_args, **kwargs: nested.append(kwargs),
    )

    parent = SimpleNamespace()
    original_render([], key="parent", continue_from=parent)

    assert calls == [
        (
            "filter classification.best.probability >= 0.8",
            {"name": "interactive DSL: parent"},
        )
    ]
    assert nested[0]["continue_from"] is previous_result
    assert editor_modes == [("parent", True)]
