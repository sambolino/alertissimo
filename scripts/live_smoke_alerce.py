#!/usr/bin/env python3

from pprint import pprint

from alertissimo.data_layer.execution import (
    EndpointRegistry,
    RegistryEndpointExecutor,
)
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.orchestration.binding import bind_workflow_run
from alertissimo.orchestration.ir import GetLightcurveStep, Source, WorkflowIR
from alertissimo.orchestration.normalization import normalize_workflow_execution
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import execute_workflow_run


TARGET = "170587117485817955"


def main():
    # 1. Semantic intent
    workflow = WorkflowIR(
        steps=[
            GetLightcurveStep(
                target_id=TARGET,
                sources=[
                    Source(
                        broker="alerce",
                        origin="lsst",
                    )
                ],
            )
        ]
    )

    print("\n=== 1. WORKFLOW ===")
    pprint(workflow.model_dump())

    # 2. Capability graph + planning
    graph = build_capability_graph()
    run = plan_workflow(workflow, graph)

    print("\n=== 2. PLANNED ===")
    for step_run in run.steps:
        print("step:", step_run.step_index, step_run.state)
        for plan in step_run.endpoint_plans:
            print(
                "  endpoint:",
                plan.broker,
                plan.origin,
                plan.endpoint,
            )

    # 3. Declarative parameter binding
    registry = EndpointRegistry()
    bindings = bind_workflow_run(run, registry)

    print("\n=== 3. BOUND ===")
    for step in bindings:
        print("step:", step.step_index)
        for call in step.bound_calls:
            print(
                "  endpoint:",
                call.endpoint_plan.broker,
                call.endpoint_plan.origin,
                call.endpoint_plan.endpoint,
            )
            print("  params:", dict(call.params))

    # 4. REAL provider execution
    executor = RegistryEndpointExecutor(registry=registry)
    executed = execute_workflow_run(run, bindings, executor)

    print("\n=== 4. EXECUTED ===")
    for step_run in executed.run.steps:
        print(
            "step:",
            step_run.step_index,
            "state:",
            step_run.state,
            "execution_ids:",
            step_run.execution_ids,
        )

    for step in executed.steps:
        for execution in step.executions:
            print("\nexecution:", execution.internal_execution_id.value)
            print(
                "physical:",
                execution.execution_provenance.broker,
                execution.execution_provenance.origin,
                execution.execution_provenance.endpoint,
            )
            print("params:", dict(execution.execution_provenance.params))

            payload = execution.payload
            if isinstance(payload, dict):
                print("payload keys:", list(payload)[:30])
            elif isinstance(payload, (list, tuple)):
                print("payload rows:", len(payload))
                if payload:
                    print("first row type:", type(payload[0]).__name__)
            else:
                print("payload type:", type(payload).__name__)

    # 5. Normalize through the real RecordBuilder/mappings
    normalized = normalize_workflow_execution(executed)

    print("\n=== 5. NORMALIZED ===")
    for step in normalized.steps:
        print("step:", step.step_index)

        for output in step.executions:
            print("\n  execution:", output.execution_id)
            for portfolio in output.portfolios:
                print("  portfolio:", portfolio.internal_portfolio_id.value)
                print("  records:", len(portfolio.records))
                print("  edges:", len(portfolio.edges))
                print("  semantic types:")
                for semantic_type in portfolio.semantic_types():
                    count = len(portfolio.records_of_type(semantic_type))
                    print(f"    {semantic_type}: {count}")

                print("\n  first few records:")
                for record in portfolio.records[:5]:
                    print(
                        "   ",
                        record.internal_record_id.value,
                        record.semantic_type,
                    )
                pprint(dict(record.fields), indent=6, width=120)

    print("\n=== SUCCESS: full live orchestration path completed ===")


if __name__ == "__main__":
    main()
