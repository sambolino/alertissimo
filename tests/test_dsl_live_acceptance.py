"""Offline tests for the all-scenarios live acceptance harness."""

from scripts import live_acceptance, live_crossmatch, live_dsl_confirm_predicate


def test_live_acceptance_scenario_names_are_unique_and_cover_current_surface():
    names = [scenario.name for scenario in live_acceptance.SCENARIOS]

    assert len(names) == len(set(names))
    assert {
        "multisurvey-discovery",
        "dsl-match-spatial",
        "dsl-cross-provider",
        "dsl-filter-candidate-flow",
        "dsl-confirm-existence-quorum",
        "dsl-confirm-predicate-quorum",
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


def test_confirm_live_scenarios_cover_existence_and_predicate_modes():
    existence = next(
        scenario
        for scenario in live_acceptance.SCENARIOS
        if scenario.name == "dsl-confirm-existence-quorum"
    )
    predicate = next(
        scenario
        for scenario in live_acceptance.SCENARIOS
        if scenario.name == "dsl-confirm-predicate-quorum"
    )

    existence_command = " ".join(existence.command(live_acceptance.REPO_ROOT))
    predicate_command = " ".join(predicate.command(live_acceptance.REPO_ROOT))

    assert existence.live is True
    assert existence.required_env == ()
    assert "live_dsl_confirm.py" in existence_command

    assert predicate.live is True
    assert predicate.required_env == ("LASAIR_ZTF_TOKEN",)
    assert "live_dsl_confirm_predicate.py" in predicate_command


def test_predicate_confirm_live_script_compiles_the_adjacent_quorum_contract():
    dsl, workflow, run = live_dsl_confirm_predicate.compile_and_plan(
        ra=live_dsl_confirm_predicate.DEFAULT_RA,
        dec=live_dsl_confirm_predicate.DEFAULT_DEC,
        radius_arcsec=live_dsl_confirm_predicate.DEFAULT_RADIUS_ARCSEC,
        quorum=live_dsl_confirm_predicate.DEFAULT_QUORUM,
    )

    live_dsl_confirm_predicate.assert_plan_contract(workflow, run)

    assert "where exists(classification.best.class)\nconfirm by 2" in dsl
    assert [step.op for step in workflow.steps] == [
        "cone_search",
        "confirm",
        "get_lightcurve",
    ]
    assert [plan.broker for plan in run.steps[1].endpoint_plans] == ["fink", "lasair"]
    assert [plan.endpoint for plan in run.steps[1].endpoint_plans] == ["objects", "objects"]


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
