from alertissimo.app_search import (
    candidate_result_key,
    cone_candidates,
    load_demo_candidate_portfolios,
    load_demo_search_data,
    load_frozen_cone_candidates,
)


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
