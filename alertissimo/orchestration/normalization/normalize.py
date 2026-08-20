"""Bridge successful orchestration results to data-layer normalization."""

from __future__ import annotations

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import Portfolio
from alertissimo.data_layer.runtime.record_builder import build_portfolios_from_execution
from alertissimo.orchestration.ir import DeriveStep, and_predicates
from alertissimo.orchestration.ir.predicates import Predicate
from alertissimo.orchestration.runtime import (
    EndpointPlan,
    EndpointPlanRef,
    StepExecutionResult,
    StepRun,
    StepRunState,
    WorkflowExecutionResult,
    WorkflowRun,
)

from .models import (
    ExecutionPortfolioResult,
    StepPortfolioResult,
    WorkflowPortfolioResult,
)
from .predicate import prune_portfolios


class WorkflowNormalizationAlignmentError(ValueError):
    """Raised before normalization when runtime results are cross-wired."""


def normalize_execution(
    execution: ExecutionResult,
    *,
    validate_semantic_model: bool = True,
) -> tuple[Portfolio, ...]:
    """Normalize exactly one physical result using the authoritative builder.

    Validation defaults on because orchestration is a production boundary from
    physical provider data into the canonical semantic model. This helper has no
    orchestration plan context, so it deliberately performs no residual pruning.
    """

    return build_portfolios_from_execution(
        execution, validate_semantic_model=validate_semantic_model
    )


def normalize_step_execution(
    result: StepExecutionResult,
    *,
    validate_semantic_model: bool = True,
) -> StepPortfolioResult:
    """Normalize a completed Step result without endpoint-plan strategy context.

    This standalone helper remains a pure normalization bridge. Workflow-level
    normalization has the aligned EndpointPlans needed to apply residual semantic
    predicates safely.
    """

    return StepPortfolioResult(
        step_index=result.step_index,
        executions=tuple(
            ExecutionPortfolioResult(
                execution_id=execution.internal_execution_id.value,
                portfolios=normalize_execution(
                    execution,
                    validate_semantic_model=validate_semantic_model,
                ),
            )
            for execution in result.executions
        ),
    )


def _plan_at(run: WorkflowRun, reference: EndpointPlanRef) -> EndpointPlan:
    try:
        step_run = run.steps[reference.step_index]
        return step_run.endpoint_plans[reference.plan_index]
    except IndexError as error:
        raise WorkflowNormalizationAlignmentError(
            "execution reuse references an unavailable endpoint plan "
            f"({reference.step_index}, {reference.plan_index})"
        ) from error


def _effective_residual(
    run: WorkflowRun,
    step_index: int,
    plan_index: int,
    *,
    visited: frozenset[tuple[int, int]] = frozenset(),
) -> Predicate | None:
    """Combine residuals inherited through execution reuse with this plan's own."""

    key = (step_index, plan_index)
    if key in visited:
        raise WorkflowNormalizationAlignmentError(
            f"execution reuse cycle detected at endpoint plan {key}"
        )
    plan = run.steps[step_index].endpoint_plans[plan_index]
    own = (
        plan.predicate_realization.residual
        if plan.predicate_realization is not None
        else None
    )
    reference = plan.execution_reuse_from
    if reference is None:
        return own
    inherited = _effective_residual(
        run,
        reference.step_index,
        reference.plan_index,
        visited=visited | {key},
    )
    return and_predicates(
        predicate for predicate in (inherited, own) if predicate is not None
    )


def _normalize_planned_execution(
    execution: ExecutionResult,
    residual: Predicate | None,
    normalized_by_execution_id: dict[str, tuple[Portfolio, ...]],
    *,
    validate_semantic_model: bool,
) -> ExecutionPortfolioResult:
    """Reuse base normalization for one physical execution, then apply a Step view.

    Coalesced semantic Steps carry the same physical execution ID. Normalizing that
    execution repeatedly would manufacture distinct Portfolio identities for the
    same physical result. The cache therefore owns the base normalized Portfolios;
    residual pruning only selects from that shared tuple and never clones them.
    """

    execution_id = execution.internal_execution_id.value
    portfolios = normalized_by_execution_id.get(execution_id)
    if portfolios is None:
        portfolios = normalize_execution(
            execution,
            validate_semantic_model=validate_semantic_model,
        )
        normalized_by_execution_id[execution_id] = portfolios
    if residual is not None:
        portfolios = prune_portfolios(portfolios, residual)
    return ExecutionPortfolioResult(
        execution_id=execution_id,
        portfolios=portfolios,
    )


def _normalize_planned_step(
    result: StepExecutionResult,
    step_run: StepRun,
    run: WorkflowRun,
    normalized_by_execution_id: dict[str, tuple[Portfolio, ...]],
    *,
    validate_semantic_model: bool,
) -> StepPortfolioResult:
    """Normalize executions against their already-validated endpoint-plan order."""

    return StepPortfolioResult(
        step_index=result.step_index,
        executions=tuple(
            _normalize_planned_execution(
                execution,
                _effective_residual(
                    run,
                    step_run.step_index,
                    plan_index,
                ),
                normalized_by_execution_id,
                validate_semantic_model=validate_semantic_model,
            )
            for plan_index, (_plan, execution) in enumerate(
                zip(step_run.endpoint_plans, result.executions)
            )
        ),
    )


def _validate_reuse_alignment(
    result: WorkflowExecutionResult,
    *,
    step_index: int,
    plan_index: int,
    plan: EndpointPlan,
    execution: ExecutionResult,
) -> None:
    reference = plan.execution_reuse_from
    if reference is None:
        return
    if reference.step_index >= step_index:
        raise WorkflowNormalizationAlignmentError(
            f"step_index {step_index} plan {plan_index} reuses a non-earlier Step"
        )
    owner_plan = _plan_at(result.run, reference)
    owner_step_result = result.steps[reference.step_index]
    try:
        owner_execution = owner_step_result.executions[reference.plan_index]
    except IndexError as error:
        raise WorkflowNormalizationAlignmentError(
            "execution reuse references an unavailable execution result "
            f"({reference.step_index}, {reference.plan_index})"
        ) from error

    if (
        owner_plan.broker,
        owner_plan.origin,
        owner_plan.endpoint,
    ) != (
        plan.broker,
        plan.origin,
        plan.endpoint,
    ):
        raise WorkflowNormalizationAlignmentError(
            "reused endpoint plan does not match owner endpoint identity"
        )
    if (
        owner_execution.internal_execution_id.value
        != execution.internal_execution_id.value
    ):
        raise WorkflowNormalizationAlignmentError(
            f"step_index {step_index} plan {plan_index} does not carry the "
            "execution ID of its declared reuse owner"
        )


def _validate_workflow_alignment(result: WorkflowExecutionResult) -> None:
    run = result.run
    if len(result.steps) != len(run.steps):
        raise WorkflowNormalizationAlignmentError(
            "execution Step result count does not match WorkflowRun StepRun count "
            f"({len(result.steps)} != {len(run.steps)})"
        )

    for position, (step_run, step_result) in enumerate(zip(run.steps, result.steps)):
        if step_result.step_index != step_run.step_index:
            raise WorkflowNormalizationAlignmentError(
                f"execution Step result at position {position} has step_index "
                f"{step_result.step_index}; expected {step_run.step_index}"
            )

        step = run.step_at(step_run.step_index)
        if isinstance(step, DeriveStep):
            if step_run.state is not StepRunState.PLANNED:
                raise WorkflowNormalizationAlignmentError(
                    f"derive step_index {step_run.step_index} is {step_run.state.value}; "
                    "it must remain planned until post-normalization derivation"
                )
            if step_run.endpoint_plans or step_run.execution_ids or step_result.executions:
                raise WorkflowNormalizationAlignmentError(
                    f"derive step_index {step_run.step_index} must have no physical "
                    "endpoint plans, execution IDs, or execution results"
                )
            continue

        if step_run.state is not StepRunState.SUCCEEDED:
            raise WorkflowNormalizationAlignmentError(
                f"step_index {step_run.step_index} is {step_run.state.value}; "
                "workflow normalization requires succeeded state"
            )
        if len(step_run.endpoint_plans) != len(step_result.executions):
            raise WorkflowNormalizationAlignmentError(
                f"step_index {step_run.step_index} endpoint plan count does not "
                "match execution result count "
                f"({len(step_run.endpoint_plans)} != "
                f"{len(step_result.executions)})"
            )
        for execution_position, (plan, execution) in enumerate(
            zip(step_run.endpoint_plans, step_result.executions)
        ):
            provenance = execution.execution_provenance
            planned_identity = (plan.broker, plan.origin, plan.endpoint)
            actual_identity = (
                provenance.broker,
                provenance.origin,
                provenance.endpoint,
            )
            if planned_identity != actual_identity:
                raise WorkflowNormalizationAlignmentError(
                    f"step_index {step_run.step_index} execution position "
                    f"{execution_position} endpoint identity does not align: "
                    f"planned broker={plan.broker}, origin={plan.origin}, "
                    f"endpoint={plan.endpoint}; actual broker={provenance.broker}, "
                    f"origin={provenance.origin}, endpoint={provenance.endpoint}"
                )
            _validate_reuse_alignment(
                result,
                step_index=step_run.step_index,
                plan_index=execution_position,
                plan=plan,
                execution=execution,
            )
        actual_ids = tuple(
            execution.internal_execution_id.value
            for execution in step_result.executions
        )
        if actual_ids != step_run.execution_ids:
            raise WorkflowNormalizationAlignmentError(
                f"step_index {step_run.step_index} execution IDs do not align in "
                f"order (StepRun has {step_run.execution_ids}, results have {actual_ids})"
            )


def normalize_workflow_execution(
    result: WorkflowExecutionResult,
    *,
    validate_semantic_model: bool = True,
) -> WorkflowPortfolioResult:
    """Normalize each physical execution once, then expose Step-specific views.

    A reused execution inherits the residual predicate of its physical owner, so a
    later semantic enrichment cannot resurrect candidates already pruned from the
    candidate-search result. Every semantic Step selects from the same base
    normalized Portfolios for a shared execution ID, preserving Portfolio identity.
    """

    _validate_workflow_alignment(result)
    normalized_by_execution_id: dict[str, tuple[Portfolio, ...]] = {}
    normalized_steps: list[StepPortfolioResult] = []
    for step_run, step_result in zip(result.run.steps, result.steps):
        step = result.run.step_at(step_run.step_index)
        if isinstance(step, DeriveStep):
            normalized_steps.append(
                normalize_step_execution(
                    step_result,
                    validate_semantic_model=validate_semantic_model,
                )
            )
            continue
        normalized_steps.append(
            _normalize_planned_step(
                step_result,
                step_run,
                result.run,
                normalized_by_execution_id,
                validate_semantic_model=validate_semantic_model,
            )
        )

    return WorkflowPortfolioResult(
        run=result.run,
        steps=tuple(normalized_steps),
    )


__all__ = [
    "WorkflowNormalizationAlignmentError",
    "normalize_execution",
    "normalize_step_execution",
    "normalize_workflow_execution",
]
