"""Provider-neutral rendering for smoke orchestration results."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any


def _object_ids(portfolio) -> list[str]:
    values = []
    for record in portfolio.records:
        for key, value in record.fields.items():
            if key == "identity.object_id" and value is not None:
                values.append(str(value))
    return sorted(set(values))


def _requested_target_ids(step) -> list[str]:
    target = getattr(step, "target", None)
    return list(target.ids) if target is not None else []


def report_data(result) -> dict[str, Any]:
    normalized_by_step = {
        step.step_index: step
        for step in (result.normalized.steps if result.normalized else ())
    }
    completed_by_step = {
        step.step_index: step
        for step in (
            result.expected_error.completed_steps if result.expected_error else ()
        )
    }
    steps = []
    for step_run, binding in zip(result.run.steps, result.bindings):
        execution_outputs = normalized_by_step.get(step_run.step_index)
        partial = completed_by_step.get(step_run.step_index)
        executions = []
        if execution_outputs:
            for output in execution_outputs.executions:
                portfolios = []
                for portfolio in output.portfolios:
                    object_ids = _object_ids(portfolio)
                    counts = Counter(
                        record.semantic_type for record in portfolio.records
                    )
                    portfolios.append(
                        {
                            "portfolio_id": portfolio.internal_portfolio_id.value,
                            "object_ids": object_ids,
                            "object_identity_available": bool(object_ids),
                            "semantic_counts": dict(sorted(counts.items())),
                            "provenance": [
                                {
                                    "execution_id": p.internal_execution_id.value,
                                    "broker": p.broker,
                                    "origin": p.origin,
                                    "endpoint": p.endpoint,
                                    "params": dict(p.params),
                                    "status": p.status,
                                }
                                for p in portfolio.executions
                            ],
                        }
                    )
                executions.append(
                    {"execution_id": output.execution_id, "portfolios": portfolios}
                )
        elif partial:
            executions = [
                {"execution_id": item.internal_execution_id.value, "portfolios": []}
                for item in partial.executions
            ]
        steps.append(
            {
                "step_index": step_run.step_index,
                "operation": result.workflow.steps[step_run.step_index].op,
                "state": step_run.state.value,
                "error": step_run.error,
                "requested_target_ids": _requested_target_ids(
                    result.workflow.steps[step_run.step_index]
                ),
                "execution_ids": list(step_run.execution_ids),
                "calls": [
                    {
                        "broker": call.endpoint_plan.broker,
                        "origin": call.endpoint_plan.origin,
                        "endpoint": call.endpoint_plan.endpoint,
                        "params": dict(call.params),
                    }
                    for call in binding.bound_calls
                ],
                "executions": executions,
            }
        )
    failed_steps = [step for step in steps if step["state"] == "failed"]
    return {
        "scenario": result.name,
        "workflow": result.workflow.name,
        "normalized_execution_count": sum(
            len(s.executions) for s in normalized_by_step.values()
        ),
        "portfolio_count": sum(
            len(e["portfolios"]) for s in steps for e in s["executions"]
        ),
        "expected_failure": result.expected_error is not None,
        "failed_step_index": failed_steps[0]["step_index"] if failed_steps else None,
        "failure_error": failed_steps[0]["error"] if failed_steps else None,
        "preserved_execution_ids": [
            execution_id for step in steps for execution_id in step["execution_ids"]
        ],
        "steps": steps,
    }


def render_json(result) -> str:
    return json.dumps(report_data(result), indent=2, sort_keys=True)


def render_human(result) -> str:
    data = report_data(result)
    lines = [f"scenario: {data['scenario']}", f"workflow: {data['workflow']}"]
    if data["expected_failure"]:
        lines.append("expected failure: yes (fail-fast contract observed)")
        lines.append(f"failed step: {data['failed_step_index']}")
        lines.append(f"error: {data['failure_error']}")
        lines.append(
            f"preserved successful execution IDs: {data['preserved_execution_ids']}"
        )
    for step in data["steps"]:
        lines.append(
            f"step/op: {step['step_index']}/{step['operation']}  runtime state: {step['state']}"
        )
        lines.append(f"  requested target IDs: {step['requested_target_ids']}")
        for call in step["calls"]:
            lines.append(
                f"  planned endpoint: {call['broker']}/{call['origin']}/{call['endpoint']}"
            )
            lines.append(f"  bound parameters: {call['params']}")
        for execution in step["executions"]:
            lines.append(f"  execution ID: {execution['execution_id']}")
            for portfolio in execution["portfolios"]:
                lines.append(f"    portfolio ID: {portfolio['portfolio_id']}")
                if portfolio["object_identity_available"]:
                    lines.append(f"    object ID: {portfolio['object_ids']}")
                else:
                    lines.append(
                        "    object identity: unavailable in normalized Portfolio"
                    )
                lines.append(
                    f"    semantic types/counts: {portfolio['semantic_counts']}"
                )
    lines.append(
        f"normalized executions: {data['normalized_execution_count']}; Portfolios: {data['portfolio_count']}"
    )
    return "\n".join(lines)
