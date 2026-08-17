"""Python-created WorkflowIR scenarios and their real orchestration pipeline."""

from __future__ import annotations

from alertissimo.orchestration.ir import TargetSelector

from dataclasses import dataclass
from typing import Callable

from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.orchestration.binding import bind_workflow_run
from alertissimo.orchestration.ir import (
    GetForcedPhotometryStep,
    GetLightcurveStep,
    Source,
    WorkflowIR,
)
from alertissimo.orchestration.normalization import normalize_workflow_execution
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import (
    WorkflowExecutionError,
    execute_workflow_run,
)

from .executors import FixtureEndpointExecutor, fixture_key

DEFAULT_TARGET = "ZTF18abbuksn"
BATCH_TARGETS = ("ZTF21abfmbix", "ZTF20acpwljl")


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    workflow: WorkflowIR
    run: object
    bindings: tuple
    normalized: object | None
    expected_error: WorkflowExecutionError | None = None


def multi_provider_workflow(targets: tuple[str, ...] = (DEFAULT_TARGET,)) -> WorkflowIR:
    if len(targets) != 1:
        raise ValueError("multi-provider requires exactly one target")
    target = targets[0]
    return WorkflowIR(
        name="multi-provider enrichment",
        steps=[
            GetLightcurveStep(
                target=TargetSelector(ids=[target], kind="object"),
                sources=[
                    Source(broker="fink", origin="ztf"),
                    Source(broker="lasair", origin="ztf"),
                ],
            ),
            GetForcedPhotometryStep(
                target=TargetSelector(ids=[target], kind="object"), sources=[Source(broker="alerce", origin="ztf")]
            ),
            GetLightcurveStep(
                target=TargetSelector(ids=[target], kind="object"), sources=[Source(broker="alerce", origin="ztf")]
            ),
        ],
    )


def multi_target_workflow(targets: tuple[str, ...] = BATCH_TARGETS) -> WorkflowIR:
    if len(targets) < 2:
        raise ValueError("multi-target requires at least two targets")
    return WorkflowIR(
        name="multi-target batch retrieval",
        steps=[
            GetLightcurveStep(
                target=TargetSelector(ids=list(targets), kind="object"), sources=[Source(broker="fink", origin="ztf")]
            ),
            GetLightcurveStep(
                target=TargetSelector(ids=list(targets), kind="object"),
                sources=[Source(broker="lasair", origin="ztf")],
            ),
        ],
    )


def partial_failure_workflow(
    targets: tuple[str, ...] = (DEFAULT_TARGET,)
) -> WorkflowIR:
    if len(targets) != 1:
        raise ValueError("partial-failure requires exactly one target")
    target = targets[0]
    return WorkflowIR(
        name="expected fail-fast partial execution",
        steps=[
            GetLightcurveStep(
                target=TargetSelector(ids=[target], kind="object"), sources=[Source(broker="fink", origin="ztf")]
            ),
            GetLightcurveStep(
                target=TargetSelector(ids=[target], kind="object"),
                sources=[
                    Source(broker="fink", origin="ztf"),
                    Source(broker="lasair", origin="ztf"),
                ],
            ),
            GetForcedPhotometryStep(
                target=TargetSelector(ids=[target], kind="object"), sources=[Source(broker="alerce", origin="ztf")]
            ),
        ],
    )


SCENARIOS: dict[str, Callable[[tuple[str, ...]], WorkflowIR]] = {
    "multi-provider": multi_provider_workflow,
    "multi-target": multi_target_workflow,
    "partial-failure": partial_failure_workflow,
}


def _fixtures(targets: tuple[str, ...]):
    csv = ",".join(targets)
    fixtures = {
        fixture_key("fink", "ztf", "objects", objectId=csv): (
            "fink_objects_single.json" if len(targets) == 1 else "fink_objects.json"
        ),
        fixture_key("lasair", "ztf", "lightcurves", objectIds=csv): (
            "lasair_lightcurves_single.json"
            if len(targets) == 1
            else "lasair_lightcurves.json"
        ),
    }
    if len(targets) == 1 and targets[0] == DEFAULT_TARGET:
        fixtures.update(
            {
                fixture_key(
                    "alerce", "ztf", "query_forced_photometry", oid=targets[0]
                ): "../../../tests/fixtures/alerce/ztf/query_forced_photometry.json",
                fixture_key(
                    "alerce", "ztf", "query_lightcurve", oid=targets[0]
                ): "../../../tests/fixtures/alerce/ztf/query_lightcurve.json",
            }
        )
    return fixtures


def run_scenario(
    name: str, *, live: bool = False, targets: tuple[str, ...] | None = None
) -> ScenarioResult:
    if targets is not None and not live:
        raise ValueError(
            "custom targets require live=True because fixture scenarios use fixed payload identifiers"
        )
    if live and name == "partial-failure":
        raise ValueError("partial-failure is intentionally fixture-only")
    factory = SCENARIOS[name]
    selected = targets or (
        BATCH_TARGETS if name == "multi-target" else (DEFAULT_TARGET,)
    )
    workflow = factory(selected)
    registry = EndpointRegistry()
    run = plan_workflow(workflow, build_capability_graph())
    bindings = bind_workflow_run(run, registry)
    executor = (
        RegistryEndpointExecutor(registry=registry)
        if live
        else FixtureEndpointExecutor(
            _fixtures(selected), fail_call=3 if name == "partial-failure" else None
        )
    )
    try:
        executed = execute_workflow_run(run, bindings, executor)
    except WorkflowExecutionError as error:
        if name != "partial-failure":
            raise
        completed = error.completed_steps
        failed = error.workflow_run.steps[1]
        if not (
            error.workflow_run.steps[0].state.value == "succeeded"
            and len(completed) == 2
            and len(completed[0].executions) == 1
            and len(completed[1].executions) == 1
            and failed.state.value == "failed"
            and failed.execution_ids
            == (completed[1].executions[0].internal_execution_id.value,)
            and "controlled fixture failure" in (failed.error or "")
        ):
            raise RuntimeError(
                "expected partial-failure state was not preserved"
            ) from error
        return ScenarioResult(name, workflow, error.workflow_run, bindings, None, error)
    if name == "partial-failure":
        raise RuntimeError("partial-failure scenario unexpectedly succeeded")
    normalized = normalize_workflow_execution(executed)
    return ScenarioResult(name, workflow, executed.run, bindings, normalized)
