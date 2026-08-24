import pytest

from alertissimo.api import DSLWorkflowService
from alertissimo.orchestration.state import (
    InMemoryWorkflowStateRepository,
    WorkflowNotFoundError,
    WorkflowStateError,
    WorkflowVersionConflictError,
)
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


def _service():
    executor = _executor()
    repository = InMemoryWorkflowStateRepository(
        workflow_id_factory=iter(("workflow:test", "workflow:second")).__next__
    )
    return DSLWorkflowService(repository=repository, executor=executor), executor


def test_service_owns_state_and_continues_by_id_and_version_only():
    service, executor = _service()

    first = service.execute_dsl(FIRST_PASS)
    assert first.workflow_id == "workflow:test"
    assert first.version == 1
    assert len(first.result.portfolios) == 1
    assert len(executor.calls) == 2

    validation = service.validate_dsl(
        CONTINUATION,
        workflow_id=first.workflow_id,
        base_version=first.version,
    )
    assert validation.is_valid
    assert validation.is_runnable
    assert len(executor.calls) == 2

    second = service.execute_dsl(
        CONTINUATION,
        workflow_id=first.workflow_id,
        base_version=first.version,
    )

    assert second.workflow_id == first.workflow_id
    assert second.version == 2
    assert len(second.result.portfolios) == 1
    assert len(executor.calls) == 3
    assert executor.calls[-1] == (
        "lasair",
        "ztf",
        "lightcurves",
        {"objectIds": CANDIDATE_ID},
    )
    assert service.repository.latest(first.workflow_id) is second


def test_service_rejects_ambiguous_or_unknown_continuation_context():
    service, executor = _service()

    with pytest.raises(WorkflowStateError, match="without workflow_id"):
        service.execute_dsl(FIRST_PASS, base_version=1)
    with pytest.raises(WorkflowStateError, match="base_version is required"):
        service.execute_dsl(CONTINUATION, workflow_id="workflow:test")
    with pytest.raises(WorkflowNotFoundError, match="unknown workflow_id"):
        service.execute_dsl(
            CONTINUATION,
            workflow_id="workflow:missing",
            base_version=1,
        )

    assert not executor.calls


def test_stale_version_fails_before_any_new_provider_call():
    service, executor = _service()
    first = service.execute_dsl(FIRST_PASS)
    second = service.execute_dsl(
        CONTINUATION,
        workflow_id=first.workflow_id,
        base_version=first.version,
    )
    calls_after_second = tuple(executor.calls)

    with pytest.raises(WorkflowVersionConflictError, match="version 2"):
        service.execute_dsl(
            "with lightcurve via fink",
            workflow_id=first.workflow_id,
            base_version=first.version,
        )

    assert second.version == 2
    assert tuple(executor.calls) == calls_after_second


def test_fresh_executions_create_independent_workflow_ids():
    service, _executor_instance = _service()

    first = service.execute_dsl(FIRST_PASS)
    second = service.execute_dsl(FIRST_PASS)

    assert first.workflow_id == "workflow:test"
    assert second.workflow_id == "workflow:second"
    assert first.workflow_id != second.workflow_id
    assert first.version == second.version == 1
