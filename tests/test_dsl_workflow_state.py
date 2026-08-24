import pytest

import alertissimo.api as api
from alertissimo.dsl import DSLParseError
from scripts.smoke.executors import FixtureEndpointExecutor, fixture_key


CANDIDATE_ID = "ZTF20acpwljl"
RA = 124.87996115142856
DEC = -6.0205001
RADIUS_ARCSEC = 5.0
FIRST_PASS = f"""objects from ztf via lasair
inside ({RA}, {DEC}, {RADIUS_ARCSEC}arcsec)
with lightcurve via fink
"""
CONTINUATION = """filter detection@ztf:fink.quality.real_bogus >= 0.8
with lightcurve via lasair
"""


def _executor() -> FixtureEndpointExecutor:
    return FixtureEndpointExecutor(
        {
            fixture_key(
                "lasair",
                "ztf",
                "cone",
                ra=RA,
                dec=DEC,
                radius=RADIUS_ARCSEC,
            ): "../../../tests/fixtures/lasair/ztf/capture_20260813T110413Z/cone_all.json",
            fixture_key(
                "fink", "ztf", "objects", objectId=CANDIDATE_ID
            ): "fink_objects_ztf20acpwljl_quality.json",
            fixture_key(
                "lasair", "ztf", "lightcurves", objectIds=CANDIDATE_ID
            ): "lasair_lightcurves_ztf20acpwljl.json",
        }
    )


def test_public_execute_dsl_retains_one_active_workflow_for_ui_continuation():
    executor = _executor()

    first = api.execute_dsl(FIRST_PASS, executor=executor)
    assert len(first.portfolios) == 1
    assert len(executor.calls) == 2

    validation = api.validate_dsl(CONTINUATION)
    assert validation.is_valid
    assert validation.is_runnable
    assert len(executor.calls) == 2

    second = api.execute_dsl(CONTINUATION, executor=executor)

    assert second.source == FIRST_PASS.rstrip() + "\n" + CONTINUATION.strip()
    assert [step.op for step in second.workflow.steps] == [
        "cone_search",
        "get_lightcurve",
        "filter",
        "get_lightcurve",
    ]
    assert len(executor.calls) == 3
    assert executor.calls[-1] == (
        "lasair",
        "ztf",
        "lightcurves",
        {"objectIds": CANDIDATE_ID},
    )


def test_complete_program_replaces_the_active_workflow():
    first_executor = _executor()
    second_executor = _executor()

    api.execute_dsl(FIRST_PASS, executor=first_executor)
    replacement = api.execute_dsl(FIRST_PASS, executor=second_executor)

    assert replacement.source == FIRST_PASS
    assert [step.op for step in replacement.workflow.steps] == [
        "cone_search",
        "get_lightcurve",
    ]
    assert len(second_executor.calls) == 2


def test_filter_cannot_be_the_first_turn_without_an_active_workflow(monkeypatch):
    executor = _executor()
    monkeypatch.setattr(api, "_active_dsl_execution", None)

    validation = api.validate_dsl(CONTINUATION)
    assert not validation.is_valid
    assert validation.parse_error is not None

    with pytest.raises(DSLParseError):
        api.execute_dsl(CONTINUATION, executor=executor)

    assert not executor.calls
