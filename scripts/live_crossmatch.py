#!/usr/bin/env python3
"""Live semantic GetCrossmatchStep acceptance against ANTARES/ZTF.

This exercises the full provider-facing semantic path:

    GetCrossmatchStep(catalog="gaia")
        -> capability validation
        -> planning
        -> target binding
        -> live provider execution
        -> normalization
        -> crossmatch@gaia:antares

A successful provider lookup that currently has no Gaia counterpart is reported as
INCONCLUSIVE (exit 3), because catalog membership is live scientific data rather
than an Alertissimo invariant.
"""

from __future__ import annotations

from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.orchestration.binding import bind_workflow_run
from alertissimo.orchestration.ir import GetCrossmatchStep, Source, TargetSelector, WorkflowIR
from alertissimo.orchestration.normalization import normalize_workflow_execution
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import execute_workflow_run


TARGET = "ZTF20aafqubg"
CATALOG = "gaia"
EXPECTED_SEMANTIC_TYPE = "crossmatch@gaia:antares"


def main() -> int:
    workflow = WorkflowIR(
        steps=[
            GetCrossmatchStep(
                target=TargetSelector(ids=[TARGET], kind="object"),
                catalog=CATALOG,
                sources=[Source(broker="antares", origin="ztf")],
            )
        ]
    )

    graph = build_capability_graph()
    run = plan_workflow(workflow, graph)

    plans = run.steps[0].endpoint_plans
    if len(plans) != 1:
        raise RuntimeError(f"expected exactly one physical plan, got {len(plans)}")
    plan = plans[0]
    expected_plan = ("antares", "ztf", "get_by_ztf_object_id")
    actual_plan = (plan.broker, plan.origin, plan.endpoint)
    if actual_plan != expected_plan:
        raise RuntimeError(
            f"unexpected crossmatch plan: expected {expected_plan!r}, got {actual_plan!r}"
        )

    registry = EndpointRegistry()
    bindings = bind_workflow_run(run, registry)
    if len(bindings) != 1 or len(bindings[0].bound_calls) != 1:
        raise RuntimeError("expected exactly one bound provider call")
    call = bindings[0].bound_calls[0]
    if dict(call.params) != {"ztf_object_id": TARGET}:
        raise RuntimeError(f"unexpected target binding: {dict(call.params)!r}")

    print("=== SEMANTIC CROSSMATCH INTENT ===")
    print(f"target:  {TARGET}")
    print(f"catalog: {CATALOG}")
    print()
    print("=== PHYSICAL REALIZATION ===")
    print(f"endpoint: {plan.broker}/{plan.origin}/{plan.endpoint}")
    print(f"params:   {dict(call.params)}")

    executor = RegistryEndpointExecutor(registry=registry)
    executed = execute_workflow_run(run, bindings, executor)
    normalized = normalize_workflow_execution(executed)

    step = normalized.steps[0]
    semantic_types = sorted(
        {
            record.semantic_type
            for portfolio in step.portfolios
            for record in portfolio.records
        }
    )
    matching_records = [
        record
        for portfolio in step.portfolios
        for record in portfolio.records
        if record.semantic_type == EXPECTED_SEMANTIC_TYPE
    ]

    print()
    print("=== NORMALIZED OUTPUT ===")
    print(f"executions: {len(step.executions)}")
    print(f"semantic portfolios: {len(step.portfolios)}")
    print(f"semantic types: {semantic_types}")
    print(f"{EXPECTED_SEMANTIC_TYPE} records: {len(matching_records)}")

    if not matching_records:
        print()
        print(
            "INCONCLUSIVE: provider lookup succeeded, but this live object currently "
            "has no normalized Gaia counterpart."
        )
        return 3

    print()
    print("OK: requested catalog selected a target-bindable crossmatch capability")
    print("OK: target ID was bound through the ANTARES survey-object contract")
    print("OK: live provider response normalized the requested Gaia crossmatch")
    print("CROSSMATCH RETRIEVAL ACCEPTANCE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
