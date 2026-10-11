import pytest

import alertissimo.api as api
from alertissimo.api import IncrementalExecutionError, execute_dsl, validate_dsl
from alertissimo.dsl import DSLParseError
from alertissimo.orchestration.runtime import WorkflowExecutionError
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
                "lasair", "ztf", "query", **LASAIR_SUMMARY_PARAMS
            ): "../../../tests/fixtures/lasair/ztf/capture_20260813T110413Z/query_core.json",
            fixture_key(
                "lasair", "ztf", "lightcurves", objectIds=CANDIDATE_ID
            ): "lasair_lightcurves_ztf20acpwljl.json",
        }
    )


def test_continuation_replays_prior_provider_calls_and_executes_only_new_enrichment():
    executor = _executor()
    first = execute_dsl(FIRST_PASS, executor=executor)
    assert len(executor.calls) == 3
    assert len(first.portfolios) == 1

    validation = validate_dsl(SECOND_PASS)
    assert validation.is_valid
    assert validation.is_runnable

    second = execute_dsl(SECOND_PASS, executor=executor)

    assert len(executor.calls) == 4
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


def test_explicit_continuation_uses_its_parent_after_another_investigation(monkeypatch):
    # Poison the compatibility context: explicit UI calls must never consult it.
    compatibility_context = object()
    monkeypatch.setattr(api, "_active_workflow", compatibility_context)
    executor = _executor()
    first = execute_dsl(FIRST_PASS, executor=executor, continue_from=None)
    other = execute_dsl(
        FIRST_PASS.replace("with lightcurve via fink\n", ""),
        executor=executor, continue_from=None,
    )
    snapshots = (first.to_dict(), other.to_dict())
    assert len(executor.calls) == 5

    validation = validate_dsl(SECOND_PASS, continue_from=first)
    assert validation.is_runnable
    assert len(executor.calls) == 5
    second = execute_dsl(SECOND_PASS, executor=executor, continue_from=first)

    assert len(executor.calls) == 6
    assert executor.calls[-1][2:] == ("lightcurves", {"objectIds": CANDIDATE_ID})
    assert tuple(second.workflow.steps[:2]) == tuple(first.workflow.steps)
    assert (first.to_dict(), other.to_dict()) == snapshots
    assert second.run.steps[0].execution_ids == first.run.steps[0].execution_ids
    assert second.run.steps[1].execution_ids == first.run.steps[1].execution_ids
    assert api._active_workflow is compatibility_context


def test_explicit_empty_context_refuses_a_fragment_even_with_an_active_workflow(monkeypatch):
    executor = _executor()
    first = execute_dsl(FIRST_PASS, executor=executor, continue_from=None)
    monkeypatch.setattr(api, "_active_workflow", first.staged)

    validation = validate_dsl(SECOND_PASS, continue_from=None)
    assert validation.parse_error is not None
    with pytest.raises(DSLParseError, match="already executed workflow"):
        execute_dsl(SECOND_PASS, executor=executor, continue_from=None)
    assert len(executor.calls) == 3
    assert api._active_workflow is first.staged


@pytest.mark.parametrize("fail_call", [2, 4], ids=["incomplete-parent", "new-call-failure"])
def test_explicit_continuation_failure_preserves_parent_and_compatibility_context(monkeypatch, fail_call):
    monkeypatch.setattr(api, "_active_workflow", None)
    executor = _executor()
    executor.fail_call = fail_call
    first = execute_dsl(FIRST_PASS, executor=executor, continue_from=None)
    snapshot = first.to_dict()

    expected = IncrementalExecutionError if fail_call == 2 else WorkflowExecutionError
    with pytest.raises(expected):
        execute_dsl(SECOND_PASS, executor=executor, continue_from=first)
    assert len(executor.calls) == (3 if fail_call == 2 else 4)
    assert first.to_dict() == snapshot
    assert api._active_workflow is None


def test_explicit_continuation_rejects_a_complete_program_without_provider_calls():
    executor = _executor()
    first = execute_dsl(FIRST_PASS, executor=executor, continue_from=None)
    validation = validate_dsl(FIRST_PASS, continue_from=first)
    assert validation.parse_error is not None
    with pytest.raises(DSLParseError, match="continuation clauses only"):
        execute_dsl(FIRST_PASS, executor=executor, continue_from=first)
    assert len(executor.calls) == 3
