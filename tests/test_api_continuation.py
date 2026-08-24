from alertissimo.api import execute_dsl, validate_dsl
from scripts.smoke.executors import FixtureEndpointExecutor, fixture_key


CANDIDATE_ID = "ZTF20acpwljl"
RA = 124.87996115142856
DEC = -6.0205001
RADIUS_ARCSEC = 5.0
FIRST_PASS = f"""objects from ztf via lasair
inside ({RA}, {DEC}, {RADIUS_ARCSEC}arcsec)
with lightcurve via fink
"""
SECOND_PASS = """filter detection@ztf:fink.quality.real_bogus >= 0.8
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


def test_continuation_replays_prior_provider_calls_and_executes_only_new_enrichment():
    executor = _executor()
    first = execute_dsl(FIRST_PASS, executor=executor)
    assert len(executor.calls) == 2
    assert len(first.portfolios) == 1

    validation = validate_dsl(SECOND_PASS)
    assert validation.is_valid
    assert validation.is_runnable

    second = execute_dsl(SECOND_PASS, executor=executor)

    assert len(executor.calls) == 3
    assert executor.calls[-1] == (
        "lasair",
        "ztf",
        "lightcurves",
        {"objectIds": CANDIDATE_ID},
    )
    assert len(second.portfolios) == 1

    semantic_types = {
        record.semantic_type
        for portfolio in second.portfolios
        for record in portfolio.records
    }
    assert any(value.startswith("detection@ztf:fink") for value in semantic_types)
    assert any(value.startswith("detection@ztf:lasair") for value in semantic_types)

    first_execution_ids = {
        execution.internal_execution_id.value
        for step in first.staged.execution.steps
        for execution in step.executions
    }
    replayed_execution_ids = {
        execution.internal_execution_id.value
        for step in second.staged.execution.steps[: len(first.staged.execution.steps)]
        for execution in step.executions
    }
    assert replayed_execution_ids == first_execution_ids


def test_complete_candidate_program_is_valid_as_a_fresh_workflow():
    executor = _executor()
    execute_dsl(FIRST_PASS, executor=executor)

    validation = validate_dsl("objects from ztf via alerce")

    assert validation.is_valid
    assert validation.is_runnable
    assert validation.compilation is not None
    assert [step.op for step in validation.compilation.workflow.steps] == [
        "semantic_search"
    ]
