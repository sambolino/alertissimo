import pytest

import alertissimo.api as api
from alertissimo.dsl import DSLParseError, SurfaceFragment
from alertissimo.orchestration.pipeline import StagedWorkflowResult
from scripts.smoke.executors import FixtureEndpointExecutor, fixture_key


CANDIDATE_ID = "ZTF20acpwljl"
RA = 124.87996115142856
DEC = -6.0205001
RADIUS_ARCSEC = 5.0
LASAIR_SUMMARY_PARAMS = {
    "selected": (
        "objects.objectId,objects.ramean,objects.decmean,objects.ncand,"
        "objects.jdmin,objects.jdmax"
    ),
    "tables": "objects",
    "limit": 100,
    "offset": 0,
    "conditions": f'objects.objectId IN ("{CANDIDATE_ID}")',
}
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
                "lasair", "ztf", "query", **LASAIR_SUMMARY_PARAMS
            ): "../../../tests/fixtures/lasair/ztf/capture_20260813T110413Z/query_core.json",
            fixture_key(
                "lasair", "ztf", "lightcurves", objectIds=CANDIDATE_ID
            ): "lasair_lightcurves_ztf20acpwljl.json",
        }
    )


def test_public_execute_dsl_retains_one_active_workflow_for_ui_continuation():
    executor = _executor()

    first = api.execute_dsl(FIRST_PASS, executor=executor)
    assert len(first.portfolios) == 1
    assert len(executor.calls) == 3
    active_before_validation = api._active_workflow

    validation = api.validate_dsl(CONTINUATION)
    assert validation.is_valid
    assert validation.is_runnable
    assert len(executor.calls) == 3
    assert api._active_workflow is active_before_validation
    assert validation.compilation is not None
    assert validation.compilation.workflow.steps[: len(first.workflow.steps)] == list(
        first.workflow.steps
    )

    second = api.execute_dsl(CONTINUATION, executor=executor)

    assert second.source == CONTINUATION
    assert isinstance(second.surface, SurfaceFragment)
    assert [step.op for step in second.workflow.steps] == [
        "cone_search",
        "get_lightcurve",
        "filter",
        "get_lightcurve",
    ]
    assert len(executor.calls) == 4
    assert executor.calls[-1] == (
        "lasair",
        "ztf",
        "lightcurves",
        {"objectIds": CANDIDATE_ID},
    )
    assert api._active_workflow is second.staged
    assert isinstance(api._active_workflow, StagedWorkflowResult)
    assert api._active_workflow.run.workflow == second.workflow
    assert not hasattr(api._active_workflow, "source")
    assert not hasattr(api._active_workflow, "surface")


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
    assert len(second_executor.calls) == 3


def test_object_lookup_starts_workflow_and_continuation_reuses_its_execution():
    target = "ZTF20aafqubg"
    executor = FixtureEndpointExecutor(
        {
            fixture_key(
                "antares",
                "ztf",
                "get_by_ztf_object_id",
                ztf_object_id=target,
            ): "../../../tests/fixtures/antares/ztf/get_by_ztf_object_id.json",
        }
    )

    first = api.execute_dsl(
        f"object {target} from ztf via antares\n",
        executor=executor,
    )
    assert [step.op for step in first.workflow.steps] == ["lookup"]
    assert len(executor.calls) == 1

    validation = api.validate_dsl("with lightcurve via antares\n")
    assert validation.is_valid
    assert validation.is_runnable

    second = api.execute_dsl("with lightcurve via antares\n", executor=executor)

    assert [step.op for step in second.workflow.steps] == [
        "lookup",
        "get_lightcurve",
    ]
    assert len(executor.calls) == 1
    assert second.run.steps[1].execution_ids == first.run.steps[0].execution_ids


def test_filter_cannot_be_the_first_turn_without_an_active_workflow(monkeypatch):
    executor = _executor()
    monkeypatch.setattr(api, "_active_workflow", None)

    validation = api.validate_dsl(CONTINUATION)
    assert not validation.is_valid
    assert validation.parse_error is not None

    with pytest.raises(DSLParseError):
        api.execute_dsl(CONTINUATION, executor=executor)

    assert not executor.calls
