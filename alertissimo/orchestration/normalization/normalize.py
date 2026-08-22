"""Bridge successful orchestration results to data-layer normalization."""

from __future__ import annotations

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import Portfolio
from alertissimo.data_layer.runtime.record_builder import build_portfolios_from_execution
from alertissimo.orchestration.ir import DeriveStep, FilterStep, MatchStep, and_predicates
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
    consolidate_portfolios,
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


def _execution_plan_indexes(
    step_run: StepRun, step_result: StepExecutionResult
) -> tuple[int, ...]:
    """Return endpoint-plan indexes corresponding to successful executions.

    Older/dense results may omit explicit index metadata; equal plan/result counts
    retain their historical positional meaning. Sparse results must provide the
    explicit indexes recorded by runtime execution.
    """

    if step_run.execution_plan_indexes:
        if len(step_run.execution_plan_indexes) != len(step_result.executions):
            raise WorkflowNormalizationAlignmentError(
                f"step_index {step_run.step_index} execution-plan index count does "
                "not match execution result count"
            )
        return step_run.execution_plan_indexes
    if len(step_run.endpoint_plans) == len(step_result.executions):
        return tuple(range(len(step_result.executions)))
    if not step_result.executions:
        return ()
    raise WorkflowNormalizationAlignmentError(
        f"step_index {step_run.step_index} has sparse execution results without "
        "execution-plan index metadata"
    )


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
    """Normalize successful executions against their owning endpoint plans."""

    plan_indexes = _execution_plan_indexes(step_run, result)
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
            for plan_index, execution in zip(plan_indexes, result.executions)
        ),
    )


def _materialize_enrichment_view(
    step_run: StepRun,
    own: StepPortfolioResult,
    normalized_steps: list[StepPortfolioResult],
) -> StepPortfolioResult:
    """Combine inherited semantic material with this Step's newly normalized data.

    ``material_input_from`` is the semantic view this targetless provider enrichment
    extends. Physical EndpointPlan candidate references remain a separate concern
    and continue to determine which object IDs are sent to provider calls. Historical
    source Steps are never mutated.
    """

    reference = step_run.material_input_from
    if reference is None:
        return own
    try:
        source = normalized_steps[reference.step_index]
    except IndexError as error:
        raise WorkflowNormalizationAlignmentError(
            f"provider step_index {step_run.step_index} references unavailable "
            f"material Step {reference.step_index}"
        ) from error
    if reference.step_index >= step_run.step_index:
        raise WorkflowNormalizationAlignmentError(
            f"provider step_index {step_run.step_index} material input must reference "
            "an earlier Step"
        )
    return StepPortfolioResult(
        step_index=own.step_index,
        executions=own.executions,
        materialized_portfolios=consolidate_portfolios(
            source.portfolios + own.portfolios
        ),
    )


def _filter_candidate_view(
    step: FilterStep,
    step_run: StepRun,
    normalized_steps: list[StepPortfolioResult],
) -> StepPortfolioResult:
    """Apply one local FilterStep to an earlier normalized semantic view.

    ``executions`` retains the historical execution grouping behavior for backward
    compatibility. ``materialized_portfolios`` is authoritative when the source is
    an accumulated semantic snapshot, so filtering never discards inherited evidence
    needed by later local or provider Steps.
    """

    reference = step_run.candidate_input_from
    if reference is None:
        raise WorkflowNormalizationAlignmentError(
            f"filter step_index {step_run.step_index} has no candidate input reference"
        )
    try:
        source = normalized_steps[reference.step_index]
    except IndexError as error:
        raise WorkflowNormalizationAlignmentError(
            f"filter step_index {step_run.step_index} references unavailable "
            f"candidate Step {reference.step_index}"
        ) from error

    if step.predicate is None:
        if step.criteria:
            raise WorkflowNormalizationAlignmentError(
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
        step_index=step_run.step_index,
        executions=executions,
        materialized_portfolios=materialized,
    )


def _execution_for_plan(
    step_run: StepRun,
    step_result: StepExecutionResult,
    plan_index: int,
) -> ExecutionResult:
    plan_indexes = _execution_plan_indexes(step_run, step_result)
    try:
        position = plan_indexes.index(plan_index)
    except ValueError as error:
        raise WorkflowNormalizationAlignmentError(
            "execution reuse references an endpoint plan with no successful execution "
            f"({step_run.step_index}, {plan_index})"
        ) from error
    return step_result.executions[position]


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
    owner_step_run = result.run.steps[reference.step_index]
    owner_step_result = result.steps[reference.step_index]
    owner_execution = _execution_for_plan(
        owner_step_run, owner_step_result, reference.plan_index
    )

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
            if (
                step_run.endpoint_plans
                or step_run.candidate_input_from is not None
                or step_run.material_input_from is not None
                or step_run.execution_ids
                or step_run.execution_plan_indexes
                or step_run.vacuous_plan_indexes
                or step_result.executions
            ):
                raise WorkflowNormalizationAlignmentError(
                    f"derive step_index {step_run.step_index} must have no physical "
                    "endpoint plans, candidate/material input, execution IDs, "
                    "execution-plan indexes, vacuous-plan indexes, or execution results"
                )
            continue

        if isinstance(step, MatchStep):
            if step_run.state is not StepRunState.PLANNED:
                raise WorkflowNormalizationAlignmentError(
                    f"match step_index {step_run.step_index} is {step_run.state.value}; "
                    "it must remain planned until post-normalization matching"
                )
            reference = step_run.candidate_input_from
            if reference is None or reference.step_index >= step_run.step_index:
                raise WorkflowNormalizationAlignmentError(
                    f"match step_index {step_run.step_index} must reference an earlier "
                    "candidate/material Step"
                )
            if (
                step_run.material_input_from is not None
                or step_run.endpoint_plans
                or step_run.execution_ids
                or step_run.execution_plan_indexes
                or step_run.vacuous_plan_indexes
                or step_result.executions
            ):
                raise WorkflowNormalizationAlignmentError(
                    f"match step_index {step_run.step_index} must have no material "
                    "input, physical endpoint plans, execution IDs, execution-plan "
                    "indexes, vacuous-plan indexes, or execution results"
                )
            continue

        if isinstance(step, FilterStep):
            if step_run.state is not StepRunState.SUCCEEDED:
                raise WorkflowNormalizationAlignmentError(
                    f"filter step_index {step_run.step_index} is {step_run.state.value}; "
                    "it must be succeeded before workflow normalization"
                )
            if step_run.candidate_input_from is None:
                raise WorkflowNormalizationAlignmentError(
                    f"filter step_index {step_run.step_index} has no candidate input"
                )
            if (
                step_run.material_input_from is not None
                or step_run.endpoint_plans
                or step_run.execution_ids
                or step_run.execution_plan_indexes
                or step_run.vacuous_plan_indexes
                or step_result.executions
            ):
                raise WorkflowNormalizationAlignmentError(
                    f"filter step_index {step_run.step_index} must have no material "
                    "input, physical endpoint plans, execution IDs, execution-plan "
                    "indexes, vacuous-plan indexes, or execution results"
                )
            continue

        if step_run.candidate_input_from is not None:
            raise WorkflowNormalizationAlignmentError(
                f"provider step_index {step_run.step_index} must not carry a StepRun "
                "candidate input; candidate IDs belong on EndpointPlans"
            )
        if step_run.material_input_from is not None:
            reference = step_run.material_input_from
            if reference.step_index >= step_run.step_index:
                raise WorkflowNormalizationAlignmentError(
                    f"provider step_index {step_run.step_index} material input must "
                    "reference an earlier Step"
                )
        if step_run.state is not StepRunState.SUCCEEDED:
            raise WorkflowNormalizationAlignmentError(
                f"step_index {step_run.step_index} is {step_run.state.value}; "
                "workflow normalization requires succeeded state"
            )

        if (
            not step_run.execution_plan_indexes
            and step_result.executions
            and len(step_run.endpoint_plans) != len(step_result.executions)
        ):
            raise WorkflowNormalizationAlignmentError(
                f"step_index {step_run.step_index} endpoint plan count does not "
                "match execution result count "
                f"({len(step_run.endpoint_plans)} != {len(step_result.executions)})"
            )

        plan_indexes = _execution_plan_indexes(step_run, step_result)
        invalid_vacuous = tuple(
            index
            for index in step_run.vacuous_plan_indexes
            if index < 0 or index >= len(step_run.endpoint_plans)
        )
        if invalid_vacuous:
            raise WorkflowNormalizationAlignmentError(
                f"step_index {step_run.step_index} vacuous endpoint plan indexes "
                f"reference unknown plans {invalid_vacuous}"
            )
        non_candidate_vacuous = tuple(
            index
            for index in step_run.vacuous_plan_indexes
            if step_run.endpoint_plans[index].candidate_input_from is None
        )
        if non_candidate_vacuous:
            raise WorkflowNormalizationAlignmentError(
                f"step_index {step_run.step_index} vacuous endpoint plan indexes "
                f"must be candidate-dependent {non_candidate_vacuous}"
            )

        overlap = tuple(
            sorted(set(plan_indexes) & set(step_run.vacuous_plan_indexes))
        )
        if overlap:
            raise WorkflowNormalizationAlignmentError(
                f"step_index {step_run.step_index} endpoint plan indexes {overlap} "
                "cannot be both executed and vacuous"
            )

        missing_plan_indexes = set(range(len(step_run.endpoint_plans))) - set(plan_indexes)
        missing_required = tuple(
            index
            for index in sorted(missing_plan_indexes)
            if step_run.endpoint_plans[index].required
            and index not in step_run.vacuous_plan_indexes
        )
        if missing_required:
            raise WorkflowNormalizationAlignmentError(
                f"step_index {step_run.step_index} is missing successful execution "
                f"results for required endpoint plan indexes {missing_required}"
            )

        for execution_position, (plan_index, execution) in enumerate(
            zip(plan_indexes, step_result.executions)
        ):
            plan = step_run.endpoint_plans[plan_index]
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
                plan_index=plan_index,
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
    normalized_execution_cache: dict[str, tuple[Portfolio, ...]] | None = None,
) -> WorkflowPortfolioResult:
    """Normalize physical executions once, then expose Step-specific semantic views.

    A reused execution inherits the residual predicate of its physical owner, so a
    later semantic enrichment cannot resurrect candidates already pruned from the
    candidate-search result. Targetless provider enrichment keeps its own physical
    executions occurrence-local while materializing an immutable semantic snapshot
    that combines the preceding material view with newly normalized evidence.
    FilterSteps select from an earlier normalized Step view without manufacturing
    physical provenance. DeriveStep and MatchStep occurrences retain empty normalized
    outputs until the ordered local semantic phase runs. Supplementary physical plans
    that failed remain visible as runtime warnings; candidate-dependent vacuous plans
    remain proven by runtime metadata.

    ``normalized_execution_cache`` may carry base, unpruned normalization already
    produced earlier in the same staged workflow invocation. Reusing that tuple is
    essential for one-shot provider iterators and also preserves stable internal
    Portfolio identities. Residual predicates remain Step-specific views and are
    never stored back as the base normalization.
    """

    _validate_workflow_alignment(result)
    normalized_by_execution_id = (
        normalized_execution_cache
        if normalized_execution_cache is not None
        else {}
    )
    normalized_steps: list[StepPortfolioResult] = []
    for step_run, step_result in zip(result.run.steps, result.steps):
        step = result.run.step_at(step_run.step_index)
        if isinstance(step, (DeriveStep, MatchStep)):
            normalized_steps.append(
                normalize_step_execution(
                    step_result,
                    validate_semantic_model=validate_semantic_model,
                )
            )
            continue
        if isinstance(step, FilterStep):
            normalized_steps.append(
                _filter_candidate_view(step, step_run, normalized_steps)
            )
            continue
        own = _normalize_planned_step(
            step_result,
            step_run,
            result.run,
            normalized_by_execution_id,
            validate_semantic_model=validate_semantic_model,
        )
        normalized_steps.append(
            _materialize_enrichment_view(step_run, own, normalized_steps)
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
