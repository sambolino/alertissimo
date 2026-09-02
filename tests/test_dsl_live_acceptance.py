"""Offline tests for the all-scenarios live acceptance harness."""

from alertissimo.api import validate_dsl

from scripts import (
    live_acceptance,
    live_crossmatch,
    live_dsl_confirm_predicate,
    live_dsl_lasair_summary,
    live_dsl_lookup,
    live_provider_lightcurves,
)


def test_live_acceptance_scenario_names_are_unique_and_cover_current_surface():
    names = [scenario.name for scenario in live_acceptance.SCENARIOS]

    assert len(names) == len(set(names))
    assert {
        "multisurvey-discovery",
        "dsl-match-spatial",
        "dsl-cross-provider",
        "dsl-lasair-compact-summary",
        "dsl-filter-candidate-flow",
        "dsl-incremental-continuation",
        "dsl-object-lookup",
        "dsl-confirm-existence-quorum",
        "dsl-confirm-predicate-quorum",
        "dsl-classification-reuse",
        "explicit-multi-provider",
        "explicit-multi-target",
        "color-magnitude-derivation",
        "alerce-lsst-lightcurve",
        "antares-ztf-lsst-lookups",
        "lasair-lsst-lightcurve",
        "antares-ztf-lightcurve",
        "antares-lsst-lightcurve",
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


def test_provider_history_lightcurve_scenarios_are_independently_runnable():
    expected = {
        "lasair-lsst-lightcurve": ("lasair-lsst", ("LASAIR_LSST_TOKEN",)),
        "antares-ztf-lightcurve": ("antares-ztf", ()),
        "antares-lsst-lightcurve": ("antares-lsst", ()),
    }
    available = {scenario.name: scenario for scenario in live_acceptance.SCENARIOS}
    for name, (case, credentials) in expected.items():
        scenario = available[name]
        command = " ".join(scenario.command(live_acceptance.REPO_ROOT))
        assert "live_provider_lightcurves.py" in command
        assert f"--case {case}" in command
        assert scenario.required_env == credentials


def test_direct_provider_lightcurve_cli_loads_dotenv(monkeypatch):
    loaded = []
    executed = []
    monkeypatch.setattr(
        live_provider_lightcurves,
        "load_dotenv",
        lambda *, override: loaded.append(override),
    )
    monkeypatch.setattr(
        live_provider_lightcurves,
        "run",
        lambda case: executed.append(case.name),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["live_provider_lightcurves.py", "--case", "lasair-lsst"],
    )

    assert live_provider_lightcurves.main() == 0
    assert loaded == [False]
    assert executed == ["lasair-lsst"]


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


def test_incremental_continuation_is_registered_as_a_live_facade_scenario():
    scenario = next(
        scenario
        for scenario in live_acceptance.SCENARIOS
        if scenario.name == "dsl-incremental-continuation"
    )

    command = " ".join(scenario.command(live_acceptance.REPO_ROOT))
    assert scenario.live is True
    assert scenario.required_env == ("LASAIR_ZTF_TOKEN",)
    assert "live_dsl_continuation.py" in command


def test_lasair_compact_summary_is_registered_and_keeps_one_semantic_step():
    scenario = next(
        scenario
        for scenario in live_acceptance.SCENARIOS
        if scenario.name == "dsl-lasair-compact-summary"
    )
    command = " ".join(scenario.command(live_acceptance.REPO_ROOT))
    assert scenario.required_env == ("LASAIR_ZTF_TOKEN",)
    assert "live_dsl_lasair_summary.py" in command

    graph = live_dsl_lasair_summary.build_capability_graph()
    dsl = f"""objects from ztf via lasair
inside ({live_dsl_lasair_summary.DEFAULT_RA}, {live_dsl_lasair_summary.DEFAULT_DEC}, 5arcsec)
"""
    workflow = live_dsl_lasair_summary.compile_surface_to_ir(
        live_dsl_lasair_summary.parse_surface_script(dsl),
        graph=graph,
    )
    run = live_dsl_lasair_summary.plan_workflow(workflow, graph)

    live_dsl_lasair_summary._assert_plan(workflow, run)
    assert [step.op for step in workflow.steps] == ["cone_search"]


def test_object_lookup_is_registered_as_two_call_public_facade_acceptance():
    scenario = next(
        scenario
        for scenario in live_acceptance.SCENARIOS
        if scenario.name == "dsl-object-lookup"
    )

    command = " ".join(scenario.command(live_acceptance.REPO_ROOT))
    assert scenario.live is True
    assert scenario.required_env == ()
    assert "live_dsl_lookup.py" in command

    validation = validate_dsl(live_dsl_lookup.FIRST_DSL)
    assert validation.is_runnable
    assert validation.compilation is not None
    lookup = validation.compilation.workflow.steps[0]
    assert lookup.op == "lookup"
    assert lookup.target.kind == "object"
    assert lookup.target.ids == [live_dsl_lookup.TARGET]


def test_predicate_confirm_live_script_compiles_the_adjacent_quorum_contract():
    dsl, workflow, run = live_dsl_confirm_predicate.compile_and_plan(
        ra=live_dsl_confirm_predicate.DEFAULT_RA,
        dec=live_dsl_confirm_predicate.DEFAULT_DEC,
        radius_arcsec=live_dsl_confirm_predicate.DEFAULT_RADIUS_ARCSEC,
        quorum=live_dsl_confirm_predicate.DEFAULT_QUORUM,
    )

    live_dsl_confirm_predicate.assert_plan_contract(workflow, run)

    assert "where exists classification.best.class\nconfirm by 2" in dsl
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
