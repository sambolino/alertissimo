from alertissimo.app_search import (
    load_demo_candidate_portfolios,
    load_demo_search_data,
)


def test_every_demo_search_result_has_a_distinct_portfolio_fixture():
    candidates, _ = load_demo_search_data()
    portfolios = load_demo_candidate_portfolios()

    object_ids = {candidate["object_id"] for candidate in candidates}
    assert object_ids <= portfolios.keys()
    assert {portfolio["diaObjectId"] for portfolio in portfolios.values()} == object_ids
    assert len({portfolio["lightCurve"][-1]["magnitude"] for portfolio in portfolios.values()}) == len(portfolios)
