"""Offline tests for the all-scenarios live acceptance harness."""

from scripts import live_acceptance, live_crossmatch


def test_live_acceptance_scenario_names_are_unique_and_cover_current_surface():
    names = [scenario.name for scenario in live_acceptance.SCENARIOS]

    assert len(names) == len(set(names))
    assert {
        "multisurvey-discovery",
        "dsl-match-spatial",
        "dsl-cross-provider",
        "dsl-filter-candidate-flow",
        "dsl-classification-reuse",
        "explicit-multi-provider",
        "explicit-multi-target",
        "color-magnitude-derivation",
        "alerce-lsst-lightcurve",
        "antares-ztf-lsst-lookups",
        "crossmatch-retrieval",
        "lasair-ztf-portfolio-html",
        "lasair-lsst-portfolio-html",
        "fink-lsst-consolidation",
        "partial-failure-control",
    } == set(names)

    partial_failure = next(
        scenario
        for scenario in live_acceptance.SCENARIOS
        if scenario.name == "partial-failure-control"
    )
    assert partial_failure.live is False


def test_crossmatch_live_scenario_is_registered_and_importable():
    scenario = next(
        scenario
        for scenario in live_acceptance.SCENARIOS
        if scenario.name == "crossmatch-retrieval"
    )

    assert live_crossmatch.TARGET == "ZTF20aafqubg"
    assert live_crossmatch.CATALOG == "gaia"
    assert live_crossmatch.EXPECTED_SEMANTIC_TYPE == "crossmatch@gaia:antares"
    assert "live_crossmatch.py" in " ".join(scenario.command(live_acceptance.REPO_ROOT))


def test_live_acceptance_status_classification_is_conservative():
    assert live_acceptance._classify(0, "all good\n") == ("PASS", "all good")
    assert live_acceptance._classify(3, "INCONCLUSIVE: sample did not overlap\n") == (
        "INCONCLUSIVE",
        "INCONCLUSIVE: sample did not overlap",
    )

    status, detail = live_acceptance._classify(
        1, "urllib.error.HTTPError: HTTP Error 504: Gateway Time-out\n"
    )
    assert status == "UNAVAILABLE"
    assert "504" in detail

    status, _detail = live_acceptance._classify(
        1, "urllib.error.HTTPError: HTTP Error 401: Unauthorized\n"
    )
    assert status == "SKIP"

    # Contract/client mistakes must not be hidden as provider availability.
    status, detail = live_acceptance._classify(
        1, "urllib.error.HTTPError: HTTP Error 400: Bad Request\n"
    )
    assert status == "FAIL"
    assert "400" in detail

    status, detail = live_acceptance._classify(
        1, "RuntimeError: semantic Step Portfolio identity mismatch\n"
    )
    assert status == "FAIL"
    assert "identity mismatch" in detail
