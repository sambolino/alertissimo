from pathlib import Path

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
)
from alertissimo.dsl.blocks import BlockRequirement, render_block_dsl
from alertissimo.orchestration.ir import ConeSearchStep


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
