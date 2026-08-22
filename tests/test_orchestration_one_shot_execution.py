"""One-shot Python-client payloads normalize once across a staged workflow."""

import json
from pathlib import Path

from alertissimo.data_layer.execution import EndpointSpec, ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
)
from alertissimo.orchestration.ir import ConeSearchStep, FilterStep, Source, WorkflowIR
from alertissimo.orchestration.normalization import summary_object_identity
from alertissimo.orchestration.pipeline import execute_staged_workflow_run
from alertissimo.orchestration.runtime import (
    CandidateInputRef,
    EndpointPlan,
    StepRun,
    StepRunState,
    WorkflowRun,
)


FIXTURE = Path(__file__).parent / "fixtures/antares/ztf/cone_search.json"


class _Registry:
    """Bind canonical cone values without importing the live ANTARES client stack."""

    def resolve(self, broker, origin, endpoint):
        assert (broker, origin, endpoint) == ("antares", "ztf", "cone_search")
        return EndpointSpec(
            broker=broker,
            origin=origin,
            endpoint=endpoint,
            transport_kind="python_client",
            method="python",
            params={
                "ra": {"required": True, "type": "number", "bind": "ra"},
                "dec": {"required": True, "type": "number", "bind": "dec"},
                "radius": {"required": True, "type": "number", "bind": "radius"},
            },
        )


class _Executor:
    def __init__(self):
        self.calls = []
        self.consumed = 0

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        del headers
        self.calls.append((broker, origin, endpoint, dict(params or {})))
        frozen_rows = json.loads(FIXTURE.read_text())

        def rows():
            for row in frozen_rows:
                self.consumed += 1
                yield row

        return ExecutionResult(
            payload=rows(),
            execution_provenance=InternalExecutionProvenance(
                internal_execution_id=InternalExecutionId("exec:one-shot"),
                broker=broker,
                origin=origin,
                endpoint=endpoint,
                params=dict(params or {}),
            ),
        )


def test_staged_candidate_read_reuses_base_antares_normalization():
    workflow = WorkflowIR(
        steps=[
            ConeSearchStep(
                semantic_type="summary",
                ra=50.84810593071894,
                dec=37.46783501531417,
                radius=1.0,
                sources=[Source(broker="antares", origin="ztf")],
            ),
            FilterStep(),
        ]
    )
    run = WorkflowRun(
        workflow=workflow,
        steps=(
            StepRun(
                step_index=0,
                state=StepRunState.PLANNED,
                endpoint_plans=(
                    EndpointPlan(
                        broker="antares",
                        origin="ztf",
                        endpoint="cone_search",
                        semantic_type="summary",
                    ),
                ),
            ),
            StepRun(
                step_index=1,
                state=StepRunState.PLANNED,
                candidate_input_from=CandidateInputRef(step_index=0),
            ),
        ),
    )
    executor = _Executor()

    staged = execute_staged_workflow_run(
        run,
        _Registry(),
        executor,
        validate_semantic_model=True,
    )

    search = staged.normalized.steps[0]
    filtered = staged.normalized.steps[1]
    search_identities = {
        summary_object_identity(portfolio) for portfolio in search.portfolios
    }
    filtered_identities = {
        summary_object_identity(portfolio) for portfolio in filtered.portfolios
    }

    # The authoritative ANTARES fixture normalizes into four execution-local
    # Portfolios. Two pairs share the same exact ZTF object identity, so the Step's
    # semantic view correctly consolidates them into two Portfolios.
    assert len(search.executions) == 1
    assert len(search.executions[0].portfolios) == 4
    assert len(search.portfolios) == 2
    assert len(search_identities) == 2
    assert filtered_identities == search_identities
    assert len(filtered.portfolios) == 2
    assert search.executions[0].execution_id == "exec:one-shot"
    assert executor.calls == [
        (
            "antares",
            "ztf",
            "cone_search",
            {"ra": 50.84810593071894, "dec": 37.46783501531417, "radius": 1.0},
        )
    ]
    # The provider generator is traversed once. Final workflow normalization reuses
    # the base Portfolio tuple instead of touching the physical payload again.
    assert executor.consumed == len(json.loads(FIXTURE.read_text()))
