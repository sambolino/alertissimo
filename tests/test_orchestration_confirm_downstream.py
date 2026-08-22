from itertools import count

from alertissimo.data_layer.execution import EndpointRegistry, ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
)
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import compile_surface_to_ir, parse_surface_script
from alertissimo.orchestration.local_semantics import finalize_local_semantics
from alertissimo.orchestration.pipeline import execute_staged_workflow_run
from alertissimo.orchestration.planner import plan_workflow


TARGET = "ZTF20acpwljl"
DSL = """objects from ztf via alerce
inside (124.87996115142856, -6.0205001, 1arcsec)
latest 1
confirm by 2 via fink, lasair
with lightcurve via fink
"""


class _ConfirmThenGetExecutor:
    def __init__(self, *, lasair_attests: bool):
        self.lasair_attests = lasair_attests
        self.calls: list[tuple[str, str, str, dict]] = []
        self._ids = count(1)

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        del headers
        params = dict(params or {})
        self.calls.append((broker, origin, endpoint, params))

        if (broker, origin, endpoint) == ("alerce", "ztf", "query_objects"):
            payload = {
                "items": [
                    {
                        "oid": TARGET,
                        "meanra": 124.87996115142856,
                        "meandec": -6.0205001,
                    }
                ]
            }
        elif (broker, origin, endpoint) == ("fink", "ztf", "objects"):
            payload = [{"i:objectId": TARGET, "i:candid": 1642249732315015013}]
        elif (broker, origin, endpoint) == ("lasair", "ztf", "objects"):
            payload = (
                [
                    {
                        "objectId": TARGET,
                        "objectData": {
                            "ncand": 2,
                            "jdmin": 2459000.5,
                            "jdmax": 2459001.5,
                            "ramean": 124.88,
                            "decmean": -6.02,
                        },
                    }
                ]
                if self.lasair_attests
                else []
            )
        else:  # pragma: no cover - the planner fixes the endpoint set.
            raise AssertionError(f"unexpected endpoint {(broker, origin, endpoint)!r}")

        return ExecutionResult(
            payload=payload,
            execution_provenance=InternalExecutionProvenance(
                internal_execution_id=InternalExecutionId(
                    f"execution:confirm:{next(self._ids)}"
                ),
                broker=broker,
                origin=origin,
                endpoint=endpoint,
                params=params,
            ),
        )


def _run(*, lasair_attests: bool):
    graph = build_capability_graph()
    workflow = compile_surface_to_ir(parse_surface_script(DSL), graph=graph)
    run = plan_workflow(workflow, graph)
    executor = _ConfirmThenGetExecutor(lasair_attests=lasair_attests)
    staged = execute_staged_workflow_run(
        run,
        EndpointRegistry(),
        executor,
        validate_semantic_model=True,
    )
    return executor, staged, finalize_local_semantics(staged.normalized)


def _summary_ids(step_view):
    return {
        str(record.fields["identity.object_id"])
        for portfolio in step_view.portfolios
        for record in portfolio.records
        if record.semantic_type.startswith("summary@")
    }


def test_confirm_quorum_survivor_is_bound_to_downstream_get():
    executor, staged, finalized = _run(lasair_attests=True)

    assert [(broker, endpoint) for broker, _, endpoint, _ in executor.calls] == [
        ("alerce", "query_objects"),
        ("fink", "objects"),
        ("lasair", "objects"),
        ("fink", "objects"),
    ]
    assert staged.bindings[3].bound_calls[0].params["objectId"] == TARGET
    assert _summary_ids(finalized.steps[1]) == {TARGET}
    assert _summary_ids(finalized.steps[2]) == {TARGET}
    assert len(finalized.steps[1].executions) == 2


def test_below_quorum_makes_downstream_get_vacuous():
    executor, staged, finalized = _run(lasair_attests=False)

    assert [(broker, endpoint) for broker, _, endpoint, _ in executor.calls] == [
        ("alerce", "query_objects"),
        ("fink", "objects"),
        ("lasair", "objects"),
    ]
    assert staged.bindings[3].bound_calls == ()
    assert staged.run.steps[3].vacuous_plan_indexes == (0,)
    assert finalized.steps[1].portfolios == ()
    assert finalized.steps[2].portfolios == ()
