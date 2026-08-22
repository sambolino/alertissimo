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
from alertissimo.orchestration.confirmation.confirm import confirm_step_portfolios
from alertissimo.orchestration.ir import ConfirmStep, DeriveStep, FilterStep, MatchStep
from alertissimo.orchestration.matching import match_step_portfolios
from alertissimo.orchestration.normalization import (
    ExecutionPortfolioResult,
    StepPortfolioResult,
    WorkflowPortfolioResult,
    consolidate_portfolios,
    normalize_execution,
    normalize_workflow_execution,
    prune_portfolios,
    summary_object_identity,
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


def _supplementary_warning(step_index: int, plan_index: int, plan, error: Exception) -> str:
    return (
        f"supplementary endpoint plan failed (step_index {step_index}, "
        f"plan_index {plan_index}, {plan.broker}/{plan.origin}/{plan.endpoint}): "
        f"{_error_description(error)}"
    )


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


def _candidate_origin(portfolio: Portfolio) -> str:
    origins = {execution.origin for execution in portfolio.executions}
    if len(origins) != 1:
        raise CandidateFlowError(
            "candidate Portfolio must retain exactly one execution origin; "
            f"found {sorted(origins)!r}"
        )
    return next(iter(origins))


def _execution_plan_indexes(
    step_run: StepRun, result: StepExecutionResult
) -> tuple[int, ...]:
    if step_run.execution_plan_indexes:
        if len(step_run.execution_plan_indexes) != len(result.executions):
            raise CandidateFlowError(
                f"candidate source step_index {step_run.step_index} has sparse "
                "execution metadata that does not match its execution results"
            )
        return step_run.execution_plan_indexes
    if len(step_run.endpoint_plans) == len(result.executions):
        return tuple(range(len(result.executions)))
    raise CandidateFlowError(
        f"candidate source step_index {step_run.step_index} is not execution-aligned"
    )


def _candidate_view_from_step(
    step_run: StepRun,
    result: StepExecutionResult,
    *,
    material_source: StepPortfolioResult | None = None,
    normalized_execution_cache: dict[str, tuple[Portfolio, ...]],
    validate_semantic_model: bool,
) -> StepPortfolioResult:
    """Build the semantic candidate/material view needed during staged execution."""

    plan_indexes = _execution_plan_indexes(step_run, result)
    executions: list[ExecutionPortfolioResult] = []
    for plan_index, execution in zip(plan_indexes, result.executions):
        plan = step_run.endpoint_plans[plan_index]
        execution_id = execution.internal_execution_id.value
        portfolios = normalized_execution_cache.get(execution_id)
        if portfolios is None:
            portfolios = normalize_execution(
                execution,
                validate_semantic_model=validate_semantic_model,
            )
            normalized_execution_cache[execution_id] = portfolios
        realization = plan.predicate_realization
        residual = realization.residual if realization is not None else None
        if residual is not None:
            portfolios = prune_portfolios(portfolios, residual)
        executions.append(
            ExecutionPortfolioResult(
                execution_id=execution_id,
                portfolios=portfolios,
            )
        )
    own = StepPortfolioResult(
        step_index=step_run.step_index,
        executions=tuple(executions),
    )
    if material_source is None:
        return own
    return StepPortfolioResult(
        step_index=step_run.step_index,
        executions=own.executions,
        materialized_portfolios=consolidate_portfolios(
            material_source.portfolios + own.portfolios
        ),
    )


def _candidate_ids_by_origin_from_view(
    view: StepPortfolioResult,
) -> dict[str, tuple[str, ...]]:
    ids_by_origin: dict[str, list[str]] = {}
    seen_by_origin: dict[str, set[str]] = {}
    for portfolio in view.portfolios:
        identity = summary_object_identity(portfolio)
        if identity is None:
            raise CandidateFlowError(
                "candidate Portfolio must expose one unambiguous summary object identity"
            )
        origin, candidate_id = identity
        seen = seen_by_origin.setdefault(origin, set())
        if candidate_id in seen:
            continue
        seen.add(candidate_id)
        ids_by_origin.setdefault(origin, []).append(candidate_id)
    return {origin: tuple(ids) for origin, ids in ids_by_origin.items()}


def _filter_view(
    step: FilterStep,
    step_index: int,
    source: StepPortfolioResult,
) -> StepPortfolioResult:
    if step.predicate is None:
        if step.criteria:
            raise CandidateFlowError(
                "legacy FilterStep criteria have no defined local predicate evaluator"
            )
        executions = source.executions
        materialized = source.portfolios
    else:
        executions = tuple(
            ExecutionPortfolioResult(
                execution_id=execution.execution_id,
                portfolios=prune_portfolios(execution.portfolios, step.predicate),
            )
            for execution in source.executions
        )
        materialized = prune_portfolios(source.portfolios, step.predicate)
    return StepPortfolioResult(
        step_index=step_index,
        executions=executions,
        materialized_portfolios=materialized,
    )


def _candidate_source_indices(run: WorkflowRun) -> frozenset[int]:
    indices = {
        reference.step_index
        for step_run in run.steps
        for plan in step_run.endpoint_plans
        for reference in [plan.candidate_input_from]
        if reference is not None
    }
    indices.update(
        step_run.candidate_input_from.step_index
        for step_run in run.steps
        if step_run.candidate_input_from is not None
    )
    indices.update(
        step_run.material_input_from.step_index
        for step_run in run.steps
        if step_run.material_input_from is not None
    )
    return frozenset(indices)


def execute_staged_workflow_run(
    run: WorkflowRun,
    registry: EndpointRegistry,
    executor: EndpointExecutor,
    *,
    validate_semantic_model: bool = True,
) -> StagedWorkflowResult:
    """Bind and execute a planned workflow as runtime values become available.

    Filter and Match may expose local candidate views early when a downstream call
    depends on them. Confirm is hybrid: its registered provider calls execute first,
    their normalized evidence is evaluated by the distinct-broker quorum, and only
    Confirm survivors become runtime targets for later provider calls. Final
    occurrence-aligned semantic views remain owned by the normal finalization phase.
    """

    if any(step.state is not StepRunState.PLANNED for step in run.steps):
        raise CandidateFlowError("staged execution requires a fully planned WorkflowRun")

    updated_run = run
    bindings: list[StepBindingResult] = []
    step_results: list[StepExecutionResult] = []
    execution_cache: dict[tuple[int, int], ExecutionResult] = {}
    normalized_execution_cache: dict[str, tuple[Portfolio, ...]] = {}
    candidate_views_by_step: dict[int, StepPortfolioResult] = {}
    candidate_ids_by_origin_by_step: dict[int, dict[str, tuple[str, ...]]] = {}
    candidate_sources = _candidate_source_indices(run)

    for original_step_run in run.steps:
        step_index = original_step_run.step_index
        step = run.step_at(step_index)

        if isinstance(step, DeriveStep):
            bindings.append(StepBindingResult(step_index=step_index, bound_calls=()))
            step_results.append(StepExecutionResult(step_index=step_index, executions=()))
            continue

        if isinstance(step, MatchStep):
            bindings.append(StepBindingResult(step_index=step_index, bound_calls=()))
            step_results.append(StepExecutionResult(step_index=step_index, executions=()))
            if step_index not in candidate_sources:
                continue
            try:
                reference = original_step_run.candidate_input_from
                if reference is None:
                    raise CandidateFlowError(
                        f"match step_index {step_index} has no candidate input reference"
                    )
                try:
                    source_view = candidate_views_by_step[reference.step_index]
                except KeyError as error:
                    raise CandidateFlowError(
                        "match candidate input is not available from referenced Step "
                        f"{reference.step_index} for step_index {step_index}"
                    ) from error
                view = match_step_portfolios(
                    step,
                    source_view,
                    step_index=step_index,
                )
                candidate_views_by_step[step_index] = view
                candidate_ids_by_origin_by_step[step_index] = (
                    _candidate_ids_by_origin_from_view(view)
                )
            except Exception as error:
                failed = original_step_run.model_copy(
                    update={
                        "state": StepRunState.FAILED,
                        "execution_ids": (),
                        "error": _error_description(error),
                    }
                )
                updated_run = _updated_run(updated_run, failed)
                raise WorkflowExecutionError(
                    f"step_index {step_index} execution failed: {_error_description(error)}",
                    workflow_run=updated_run,
                    completed_steps=tuple(step_results),
                ) from error
            continue

        if isinstance(step, FilterStep):
            binding = StepBindingResult(step_index=step_index, bound_calls=())
            bindings.append(binding)
            result = StepExecutionResult(step_index=step_index, executions=())
            step_results.append(result)
            try:
                reference = original_step_run.candidate_input_from
                if reference is None:
                    raise CandidateFlowError(
                        f"filter step_index {step_index} has no candidate input reference"
                    )
                try:
                    source_view = candidate_views_by_step[reference.step_index]
                except KeyError as error:
                    raise CandidateFlowError(
                        "filter candidate input is not available from referenced Step "
                        f"{reference.step_index} for step_index {step_index}"
                    ) from error
                view = _filter_view(step, step_index, source_view)
                candidate_views_by_step[step_index] = view
                candidate_ids_by_origin_by_step[step_index] = (
                    _candidate_ids_by_origin_from_view(view)
                )
            except Exception as error:
                failed = original_step_run.model_copy(
                    update={
                        "state": StepRunState.FAILED,
                        "execution_ids": (),
                        "error": _error_description(error),
                    }
                )
                updated_run = _updated_run(updated_run, failed)
                raise WorkflowExecutionError(
                    f"step_index {step_index} execution failed: {_error_description(error)}",
                    workflow_run=updated_run,
                    completed_steps=tuple(step_results),
                ) from error

            succeeded = original_step_run.model_copy(
                update={
                    "state": StepRunState.SUCCEEDED,
                    "execution_ids": (),
                    "error": None,
                }
            )
            updated_run = _updated_run(updated_run, succeeded)
            continue

        candidate_plan_indexes = tuple(
            plan_index
            for plan_index, plan in enumerate(original_step_run.endpoint_plans)
            if plan.candidate_input_from is not None
        )
        if (
            candidate_plan_indexes
            and len(candidate_plan_indexes) == len(original_step_run.endpoint_plans)
            and all(
                not candidate_ids_by_origin_by_step.get(
                    original_step_run.endpoint_plans[plan_index].candidate_input_from.step_index
                )
                for plan_index in candidate_plan_indexes
            )
        ):
            binding = StepBindingResult(step_index=step_index, bound_calls=())
            bindings.append(binding)
            result = StepExecutionResult(step_index=step_index, executions=())
            step_results.append(result)
            succeeded = original_step_run.model_copy(
                update={
                    "state": StepRunState.SUCCEEDED,
                    "execution_ids": (),
                    "vacuous_plan_indexes": candidate_plan_indexes,
                    "error": None,
                }
            )
            updated_run = _updated_run(updated_run, succeeded)
            if step_index in candidate_sources:
                material_source = None
                reference = succeeded.material_input_from
                if reference is not None:
                    material_source = candidate_views_by_step.get(reference.step_index)
                view = StepPortfolioResult(
                    step_index=step_index,
                    executions=(),
                    materialized_portfolios=(
                        material_source.portfolios if material_source is not None else None
                    ),
                )
                if isinstance(step, ConfirmStep):
                    source_reference = succeeded.candidate_input_from
                    if source_reference is None:
                        raise CandidateFlowError(
                            f"confirm step_index {step_index} has no candidate input reference"
                        )
                    source_view = candidate_views_by_step[source_reference.step_index]
                    view = confirm_step_portfolios(
                        step,
                        source_view,
                        StepPortfolioResult(step_index=step_index, executions=()),
                        step_index=step_index,
                    )
                candidate_views_by_step[step_index] = view
                candidate_ids_by_origin_by_step[step_index] = (
                    _candidate_ids_by_origin_from_view(view)
                    if view.portfolios
                    else {}
                )
            continue

        calls = []
        call_plan_indexes: list[int] = []
        vacuous_plan_indexes: list[int] = []
        for plan_index, plan in enumerate(original_step_run.endpoint_plans):
            runtime_values = None
            reference = plan.candidate_input_from
            if reference is not None:
                try:
                    candidate_ids_by_origin = candidate_ids_by_origin_by_step[
                        reference.step_index
                    ]
                except KeyError as error:
                    raise CandidateFlowError(
                        "candidate input is not available from referenced Step "
                        f"{reference.step_index} for step_index {step_index}"
                    ) from error
                candidate_ids = candidate_ids_by_origin.get(plan.origin, ())
                if not candidate_ids:
                    vacuous_plan_indexes.append(plan_index)
                    continue
                runtime_values = {"target_id": candidate_ids}
            calls.append(
                bind_endpoint(
                    step,
                    plan,
                    registry,
                    runtime_values=runtime_values,
                )
            )
            call_plan_indexes.append(plan_index)
        binding = StepBindingResult(step_index=step_index, bound_calls=tuple(calls))
        bindings.append(binding)

        executions: list[ExecutionResult] = []
        execution_plan_indexes: list[int] = []
        warnings: list[str] = []
        for plan_index, call in zip(call_plan_indexes, binding.bound_calls):
            plan = call.endpoint_plan
            try:
                reference = plan.execution_reuse_from
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
            except Exception as error:
                if not plan.required:
                    warnings.append(
                        _supplementary_warning(step_index, plan_index, plan, error)
                    )
                    continue

                partial = StepExecutionResult(
                    step_index=step_index, executions=tuple(executions)
                )
                step_results.append(partial)
                failed = original_step_run.model_copy(
                    update={
                        "state": StepRunState.FAILED,
                        "execution_ids": tuple(
                            execution.internal_execution_id.value for execution in executions
                        ),
                        "execution_plan_indexes": tuple(execution_plan_indexes),
                        "vacuous_plan_indexes": tuple(vacuous_plan_indexes),
                        "warnings": tuple(warnings),
                        "error": _error_description(error),
                    }
                )
                updated_run = _updated_run(updated_run, failed)
                raise WorkflowExecutionError(
                    f"step_index {step_index} execution failed: {_error_description(error)}",
                    workflow_run=updated_run,
                    completed_steps=tuple(step_results),
                ) from error

            executions.append(execution)
            execution_plan_indexes.append(plan_index)
            execution_cache[(step_index, plan_index)] = execution

        result = StepExecutionResult(step_index=step_index, executions=tuple(executions))
        step_results.append(result)
        succeeded = original_step_run.model_copy(
            update={
                "state": StepRunState.SUCCEEDED,
                "execution_ids": tuple(
                    execution.internal_execution_id.value for execution in executions
                ),
                "execution_plan_indexes": tuple(execution_plan_indexes),
                "vacuous_plan_indexes": tuple(vacuous_plan_indexes),
                "warnings": tuple(warnings),
                "error": None,
            }
        )
        updated_run = _updated_run(updated_run, succeeded)

        if step_index in candidate_sources:
            material_source = None
            reference = succeeded.material_input_from
            if reference is not None:
                try:
                    material_source = candidate_views_by_step[reference.step_index]
                except KeyError as error:
                    raise CandidateFlowError(
                        "semantic material input is not available from referenced Step "
                        f"{reference.step_index} for step_index {step_index}"
                    ) from error
            view = _candidate_view_from_step(
                succeeded,
                result,
                material_source=material_source,
                normalized_execution_cache=normalized_execution_cache,
                validate_semantic_model=validate_semantic_model,
            )
            if isinstance(step, ConfirmStep):
                source_reference = succeeded.candidate_input_from
                if source_reference is None:
                    raise CandidateFlowError(
                        f"confirm step_index {step_index} has no candidate input reference"
                    )
                try:
                    source_view = candidate_views_by_step[source_reference.step_index]
                except KeyError as error:
                    raise CandidateFlowError(
                        "confirm candidate input is not available from referenced Step "
                        f"{source_reference.step_index} for step_index {step_index}"
                    ) from error
                view = confirm_step_portfolios(
                    step,
                    source_view,
                    StepPortfolioResult(
                        step_index=step_index,
                        executions=view.executions,
                    ),
                    step_index=step_index,
                )
            candidate_views_by_step[step_index] = view
            candidate_ids_by_origin_by_step[step_index] = (
                _candidate_ids_by_origin_from_view(view)
            )

    execution_result = WorkflowExecutionResult(
        run=updated_run,
        steps=tuple(step_results),
    )
    normalized = normalize_workflow_execution(
        execution_result,
        validate_semantic_model=validate_semantic_model,
        normalized_execution_cache=normalized_execution_cache,
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
