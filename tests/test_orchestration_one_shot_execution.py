"""One-shot Python-client payloads remain stable across staged normalization reads."""

import json
from pathlib import Path

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
)
from alertissimo.orchestration.ir import ConeSearchStep, Source, WorkflowIR
from alertissimo.orchestration.normalization import (
    normalize_execution,
    normalize_workflow_execution,
    summary_object_identity,
)
from alertissimo.orchestration.runtime import (
    EndpointPlan,
    StepExecutionResult,
    StepRun,
    StepRunState,
    WorkflowExecutionResult,
    WorkflowRun,
)


FIXTURE = Path(__file__).parent / "fixtures/antares/ztf/cone_search.json"


def _execution(payload) -> ExecutionResult:
    return ExecutionResult(
        payload=payload,
        execution_provenance=InternalExecutionProvenance(
            internal_execution_id=InternalExecutionId("exec:one-shot"),
            broker="antares",
            origin="ztf",
            endpoint="cone_search",
        ),
    )


def test_execution_result_wraps_iterator_lazily_and_replays_rows():
    consumed: list[int] = []

    def rows():
        for value in (1, 2, 3):
            consumed.append(value)
            yield value

    execution = _execution(rows())
    assert consumed == []
    assert tuple(execution.payload) == (1, 2, 3)
    assert consumed == [1, 2, 3]
    assert tuple(execution.payload) == (1, 2, 3)
    assert consumed == [1, 2, 3]


def test_staged_candidate_read_does_not_empty_final_antares_normalization():
    frozen_rows = json.loads(FIXTURE.read_text())
    execution = _execution((row for row in frozen_rows))

    # Staged orchestration performs this first read to expose runtime candidate IDs.
    staged_portfolios = normalize_execution(execution, validate_semantic_model=True)
    staged_identities = {
        summary_object_identity(portfolio) for portfolio in staged_portfolios
    }
    assert len(staged_portfolios) == 4

    workflow = WorkflowIR(
        steps=[
            ConeSearchStep(
                semantic_type="summary",
                ra=50.84810593071894,
                dec=37.46783501531417,
                radius=1.0,
                sources=[Source(broker="antares", origin="ztf")],
            )
        ]
    )
    plan = EndpointPlan(
        broker="antares",
        origin="ztf",
        endpoint="cone_search",
        semantic_type="summary",
    )
    run = WorkflowRun(
        workflow=workflow,
        steps=(
            StepRun(
                step_index=0,
                state=StepRunState.SUCCEEDED,
                endpoint_plans=(plan,),
                execution_ids=("exec:one-shot",),
                execution_plan_indexes=(0,),
            ),
        ),
    )
    result = WorkflowExecutionResult(
        run=run,
        steps=(StepExecutionResult(step_index=0, executions=(execution,)),),
    )

    final = normalize_workflow_execution(result, validate_semantic_model=True)
    final_portfolios = final.steps[0].portfolios
    final_identities = {
        summary_object_identity(portfolio) for portfolio in final_portfolios
    }

    assert len(final_portfolios) == 4
    assert final_identities == staged_identities
