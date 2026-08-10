from examples.build_lasair_portfolio import build_example_portfolio


def test_lasair_example_has_concrete_types_and_no_inferred_edges():
    portfolio = build_example_portfolio()
    semantic_types = {record.semantic_type for record in portfolio.records}

    assert "crossmatch@{producer}:lasair" not in semantic_types
    assert "crossmatch@sherlock:lasair" not in semantic_types
    assert "crossmatch@unknown:lasair" in semantic_types
    assert portfolio.edges == ()
