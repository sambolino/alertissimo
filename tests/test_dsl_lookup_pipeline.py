"""End-to-end DSL lookup ownership, fan-out, filtering, and enrichment tests."""

from __future__ import annotations

from copy import deepcopy
from itertools import count
import json
from pathlib import Path

from alertissimo.data_layer.execution import EndpointRegistry, ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
)
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import compile_surface_to_ir, parse_surface_script
from alertissimo.orchestration.pipeline import execute_staged_workflow_run
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import CandidateInputRef


OBJECT_A = "ZTF-LOOKUP-A"
OBJECT_B = "ZTF-LOOKUP-B"


class _LookupFlowExecutor:
    def __init__(self) -> None:
        fixture_path = (
            Path(__file__).parent
            / "fixtures"
            / "antares"
            / "ztf"
            / "get_by_ztf_object_id.json"
        )
        self.template = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.calls: list[tuple[str, str, str, dict[str, object]]] = []
        self._ids = count(1)

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        del headers
        supplied = dict(params or {})
        self.calls.append((broker, origin, endpoint, supplied))

        if (broker, origin, endpoint) == (
            "antares",
            "ztf",
            "get_by_ztf_object_id",
        ):
            object_id = supplied["ztf_object_id"]
            payload = deepcopy(self.template)
            payload["properties"]["ztf_object_id"] = object_id
            payload["properties"]["survey"]["ztf"]["id"] = [object_id]
            payload["locus_id"] = f"ANT-{object_id}"
            payload["ra"] = 50.0 if object_id == OBJECT_A else 10.0
        elif (broker, origin, endpoint) == ("lasair", "ztf", "lightcurves"):
            assert supplied == {"objectIds": OBJECT_A}
            payload = [
                {
                    "objectId": OBJECT_A,
                    "candidates": [
                        {
                            "candid": 1,
                            "jd": 2459001.5,
                            "fid": 1,
                            "ra": 50.0,
                            "dec": -2.0,
                            "magpsf": 19.0,
                            "sigmapsf": 0.1,
                        }
                    ],
                }
            ]
        else:
            raise AssertionError(
                f"unexpected physical call: {broker}/{origin}/{endpoint}"
            )

        return ExecutionResult(
            payload=payload,
            execution_provenance=InternalExecutionProvenance(
                internal_execution_id=InternalExecutionId(
                    f"execution:lookup:{next(self._ids)}"
                ),
                broker=broker,
                origin=origin,
                endpoint=endpoint,
                params=supplied,
            ),
        )


def _object_ids(step_output) -> tuple[str, ...]:
    found: list[str] = []
    for execution in step_output.executions:
        for portfolio in execution.portfolios:
            for record in portfolio.records:
                value = dict(record.fields).get("identity.object_id")
                if value is not None and value not in found:
                    found.append(value)
    return tuple(found)


def test_plural_lookup_owns_candidates_fans_out_filters_and_binds_survivors():
    source = f"""objects {OBJECT_A}, {OBJECT_B} from ztf via antares
filter summary@ztf:antares.position.ra >= 40
with lightcurve via lasair
"""
    graph = build_capability_graph()
    workflow = compile_surface_to_ir(
        parse_surface_script(source), graph=graph, name="lookup candidate flow"
    )
    run = plan_workflow(workflow, graph)

    assert [step.op for step in workflow.steps] == [
        "lookup",
        "filter",
        "get_lightcurve",
    ]
    lookup = workflow.steps[0]
    assert lookup.target.kind == "object"
    assert lookup.target.ids == [OBJECT_A, OBJECT_B]
    assert run.steps[1].candidate_input_from == CandidateInputRef(step_index=0)
    assert run.steps[2].endpoint_plans[0].candidate_input_from == CandidateInputRef(
        step_index=1
    )

    executor = _LookupFlowExecutor()
    staged = execute_staged_workflow_run(run, EndpointRegistry(), executor)

    assert executor.calls == [
        (
            "antares",
            "ztf",
            "get_by_ztf_object_id",
            {"ztf_object_id": OBJECT_A},
        ),
        (
            "antares",
            "ztf",
            "get_by_ztf_object_id",
            {"ztf_object_id": OBJECT_B},
        ),
        ("lasair", "ztf", "lightcurves", {"objectIds": OBJECT_A}),
    ]
    assert staged.bindings[0].plan_indexes == (0, 0)
    assert staged.run.steps[0].execution_plan_indexes == (0, 0)
    assert _object_ids(staged.normalized.steps[0]) == (OBJECT_A, OBJECT_B)
    assert _object_ids(staged.normalized.steps[1]) == (OBJECT_A,)
    assert _object_ids(staged.normalized.steps[2]) == (OBJECT_A,)
