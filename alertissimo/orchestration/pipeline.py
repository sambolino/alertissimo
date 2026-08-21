"""High-level staged orchestration for runtime workflow dependencies.

The lower-level planner, binder, executor, and normalizer remain independently
usable. This driver composes them when later physical calls need semantic values
that only exist after an earlier Step has executed and normalized.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from alertissimo.data_layer.execution import EndpointRegistry, ExecutionResult
from alertissimo.data_layer.representations import Portfolio
from alertissimo.orchestration.binding import bind_endpoint
from alertissimo.orchestration.binding.models import StepBindingResult
from alertissimo.orchestration.ir import DeriveStep
from alertissimo.orchestration.normalization import (
    WorkflowPortfolioResult,
    normalize_execution,
    normalize_workflow_execution,
    prune_portfolios,
)
from alertissimo.orchestration.runtime import (
    StepExecutionResult,
    StepRun,
    StepRunState,
    WorkflowExecutionError,
    WorkflowExecutionResult,
    WorkflowRun,
    execute_bound_call,
)


class EndpointExecutor(Protocol):
    def execute(self, broker: str, origin: str, endpoint: str, params=None, headers=None) -> ExecutionResult: ...


class CandidateFlowError(ValueError):
    """Runtime candidate output cannot safely supply a dependent endpoint call."""


@dataclass(frozen=True)
class StagedWorkflowResult:
    """One fully executed staged workflow plus its occurrence-aligned products."""

    execution: WorkflowExecutionResult
    bindings: tuple[StepBindingResult, ...]
    normalized: WorkflowPortfolioResult

    @property
    def run(self) -> WorkflowRun:
        return self.execution.run


def _updated_run(run: WorkflowRun, step: StepRun) -> WorkflowRun:
    steps = list(run.steps)
    steps[step.step_index] = step
    return run.model_copy(update={"steps": tuple(steps)})


def _error_description(error: Exception) -> str:
    detail = str(error).strip()
    return f"{type(error).__name__}: {detail}" if detail else type(error).__name__


def _candidate_id(portfolio: Portfolio) -> str:
    values = {
        str(value)
        for record in portfolio.records
        if record.semantic_type.split("@", 1)[0] == "summary"
        for key, value in record.fields.items()
        if key == "identity.object_id" and value is not None
    }
    if len(values) != 1:
        raise CandidateFlowError(
            "candidate Portfolio must expose exactly one summary.identity.object_id; "
            f"found {sorted(values)!r}"
        )
    return next(iter(values))


def _candidate_ids_from_step(
    step_run: StepRun,
    result: StepExecutionResult,
    *,
    validate_semantic_model: bool,
) -> tuple[str, ...]:
    """Read object candidate identities only from normalized semantic Portfolios."""

    if len(step_run.endpoint_plans) != len(result.executions):
        raise CandidateFlowError(
            f"candidate source step_index {step_run.step_index} is not execution-aligned"
        )

    ids: list[str] = []
    seen: set[str] = set()
    for plan, execution in zip(step_run.endpoint_plans, result.executions):
        portfolios = normalize_execution(
            execution,
            validate_semantic_model=validate_semantic_model,
        )
        realization = plan.predicate_realization
        residual = realization.residual if realization is not None else None
        if residual is not None:
            portfolios = prune_portfolios(portfolios, residual)
        for portfolio in portfolios:
            candidate_id = _candidate_id(portfolio)
            if candidate_id in seen:
                continue
            seen.add(candidate_id)
            ids.append(candidate_id)
    return tuple(ids)


def _candidate_source_indices(run: WorkflowRun) -> frozenset[int]:
    return frozenset(
        reference.step_index
        for step_run in run.steps
        for plan in step_run.endpoint_plans
        for reference in [plan.candidate_input_from]
        if reference is not None
    )


def execute_staged_workflow_run(
    run: WorkflowRun,
    registry: EndpointRegistry,
    executor: EndpointExecutor,
    *,
    validate_semantic_model: bool = True,
) -> StagedWorkflowResult:
    """Bind and execute a planned workflow as runtime values become available.

    Plans without runtime dependencies are bound normally. A plan carrying
    ``candidate_input_from`` receives ``target_id`` from the referenced Step's
    normalized candidate Portfolios. A plan carrying ``execution_reuse_from``
    still reuses the owner's physical execution and owns no new invocation.

    The semantic WorkflowIR is never rewritten with discovered IDs.
    """

    if any(step.state is not StepRunState.PLANNED for step in run.steps):
        raise CandidateFlowError("staged execution requires a fully planned WorkflowRun")

    updated_run = run
    bindings: list[StepBindingResult] = []
    step_results: list[StepExecutionResult] = []
    execution_cache: dict[tuple[int, int], ExecutionResult] = {}
    candidate_ids_by_step: dict[int, tuple[str, ...]] = {}
    candidate_sources = _candidate_source_indices(run)

    for original_step_run in run.steps:
        step_index = original_step_run.step_index
        step = run.step_at(step_index)

        if isinstance(step, DeriveStep):
            bindings.append(StepBindingResult(step_index=step_index, bound_calls=()))
            step_results.append(StepExecutionResult(step_index=step_index, executions=()))
            continue

        # Every plan of a targetless candidate enrichment refers to the same
        # semantic candidate set. If it is empty, the semantic retrieval succeeds
        # vacuously without manufacturing a provider call.
        candidate_references = tuple(
            plan.candidate_input_from
            for plan in original_step_run.endpoint_plans
            if plan.candidate_input_from is not None
        )
        if candidate_references and all(
            candidate_ids_by_step.get(reference.step_index) == ()
            for reference in candidate_references
        ):
            binding = StepBindingResult(step_index=step_index, bound_calls=())
            bindings.append(binding)
            result = StepExecutionResult(step_index=step_index, executions=())
            step_results.append(result)
            succeeded = original_step_run.model_copy(
                update={
                    "state": StepRunState.SUCCEEDED,
                    "execution_ids": (),
                    "error": None,
                }
            )
            updated_run = _updated_run(updated_run, succeeded)
            continue

        calls = []
        for plan in original_step_run.endpoint_plans:
            runtime_values = None
            reference = plan.candidate_input_from
            if reference is not None:
                try:
                    candidate_ids = candidate_ids_by_step[reference.step_index]
                except KeyError as error:
                    raise CandidateFlowError(
                        "candidate input is not available from referenced Step "
                        f"{reference.step_index} for step_index {step_index}"
                    ) from error
                runtime_values = {"target_id": candidate_ids}
            calls.append(
                bind_endpoint(
                    step,
                    plan,
                    registry,
                    runtime_values=runtime_values,
                )
            )
        binding = StepBindingResult(step_index=step_index, bound_calls=tuple(calls))
        bindings.append(binding)

        executions: list[ExecutionResult] = []
        try:
            for plan_index, call in enumerate(binding.bound_calls):
                reference = call.endpoint_plan.execution_reuse_from
                if reference is None:
                    execution = execute_bound_call(call, executor)  # type: ignore[arg-type]
                else:
                    key = (reference.step_index, reference.plan_index)
                    try:
                        execution = execution_cache[key]
                    except KeyError as error:
                        raise CandidateFlowError(
                            "reused execution is not available from its declared owner "
                            f"{key}"
                        ) from error
                executions.append(execution)
                execution_cache[(step_index, plan_index)] = execution
        except Exception as error:
            partial = StepExecutionResult(step_index=step_index, executions=tuple(executions))
            step_results.append(partial)
            failed = original_step_run.model_copy(
                update={
                    "state": StepRunState.FAILED,
                    "execution_ids": tuple(
                        execution.internal_execution_id.value for execution in executions
                    ),
                    "error": _error_description(error),
                }
            )
            updated_run = _updated_run(updated_run, failed)
            raise WorkflowExecutionError(
                f"step_index {step_index} execution failed: {_error_description(error)}",
                workflow_run=updated_run,
                completed_steps=tuple(step_results),
            ) from error

        result = StepExecutionResult(step_index=step_index, executions=tuple(executions))
        step_results.append(result)
        succeeded = original_step_run.model_copy(
            update={
                "state": StepRunState.SUCCEEDED,
                "execution_ids": tuple(
                    execution.internal_execution_id.value for execution in executions
                ),
                "error": None,
            }
        )
        updated_run = _updated_run(updated_run, succeeded)

        if step_index in candidate_sources:
            candidate_ids_by_step[step_index] = _candidate_ids_from_step(
                succeeded,
                result,
                validate_semantic_model=validate_semantic_model,
            )

    execution_result = WorkflowExecutionResult(
        run=updated_run,
        steps=tuple(step_results),
    )
    normalized = normalize_workflow_execution(
        execution_result,
        validate_semantic_model=validate_semantic_model,
    )
    return StagedWorkflowResult(
        execution=execution_result,
        bindings=tuple(bindings),
        normalized=normalized,
    )


__all__ = [
    "CandidateFlowError",
    "StagedWorkflowResult",
    "execute_staged_workflow_run",
]
