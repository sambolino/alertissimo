"""Deterministically select registered endpoints for provider-facing IR steps.

Capability validation determines *what can* satisfy an intent; this planner
chooses endpoint identities from that evidence.  It deliberately does not bind
generic IR arguments to physical parameter names or invoke an ``EndpointSpec``.
The later boundaries are therefore: planning -> parameter binding -> execution.
"""

from __future__ import annotations

from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraph,
    EndpointCapability,
)
from alertissimo.orchestration.ir.models import DeriveStep, Source, Step, WorkflowIR
from alertissimo.orchestration.runtime.models import (
    EndpointPlan,
    StepRun,
    StepRunState,
    WorkflowRun,
)
from alertissimo.orchestration.validation import (
    CapabilityValidationResult,
    SourceCapabilityResult,
    validate_step_capabilities,
)


class PlanningError(ValueError):
    """Base class for failures to select a physical endpoint identity."""


class PlanningAmbiguityError(PlanningError):
    """Raised when selection would require an as-yet undefined ranking policy."""


class UnsupportedStepError(PlanningError):
    """Raised when registry capabilities cannot satisfy a provider-facing step."""


class PlanningDeferredError(PlanningError):
    """Raised when safe planning depends on capability semantics not yet modeled."""


class PlanningNotApplicableError(PlanningError):
    """Raised for a local/orchestration step that needs no provider endpoint."""


def _source_text(source: Source | None) -> str:
    if source is None:
        return "unconstrained"
    return f"broker={source.broker or '*'}, origin={source.origin or '*'}"


def _candidate_text(candidates: tuple[EndpointCapability, ...]) -> str:
    return ", ".join(
        f"{item.broker}/{item.origin}/{item.endpoint}" for item in candidates
    )


def _context(result: CapabilityValidationResult) -> str:
    semantic = (
        f", semantic_type={result.semantic_type!r}"
        if result.semantic_type is not None
        else ""
    )
    return f"operation={result.operation!r}{semantic}"


def _unsupported(result: CapabilityValidationResult) -> UnsupportedStepError:
    failures = "; ".join(
        f"{_source_text(item.source)}: {item.reason}"
        for item in result.source_results
        if item.status == "unsupported"
    )
    return UnsupportedStepError(
        f"unsupported provider step ({_context(result)}): {failures or result.reason}"
    )


def _select_one(
    result: CapabilityValidationResult, source_result: SourceCapabilityResult
) -> EndpointCapability:
    candidates = source_result.candidates
    if len(candidates) != 1:
        raise PlanningAmbiguityError(
            f"ambiguous provider endpoint ({_context(result)}, "
            f"source={_source_text(source_result.source)}); candidates: "
            f"{_candidate_text(candidates)}"
        )
    return candidates[0]


def plan_step(step: Step, graph: CapabilityGraph) -> tuple[EndpointPlan, ...]:
    """Select provider endpoints, or register a DeriveStep as endpoint-free."""
    validation = validate_step_capabilities(step, graph)
    if validation.status == "not_applicable":
        if isinstance(step, DeriveStep):
            return ()
        raise PlanningNotApplicableError(
            f"provider endpoint planning is not applicable ({_context(validation)}): "
            f"{validation.reason}"
        )
    if validation.status == "deferred":
        raise PlanningDeferredError(
            f"provider endpoint planning is deferred ({_context(validation)}): "
            f"{validation.reason}"
        )
    if validation.status == "unsupported":
        raise _unsupported(validation)

    selected = tuple(
        _select_one(validation, item) for item in validation.source_results
    )
    return tuple(
        EndpointPlan(
            broker=item.broker,
            origin=item.origin,
            endpoint=item.endpoint,
            semantic_type=validation.semantic_type,
        )
        for item in selected
    )


def plan_workflow(workflow: WorkflowIR, graph: CapabilityGraph) -> WorkflowRun:
    """Plan provider calls while retaining endpoint-free derive occurrences.

    Planning remains fail-fast for deferred, ambiguous, unsupported, or other
    local orchestration steps.  A DeriveStep is the deliberate exception: its
    occurrence is planned with zero endpoint plans and executes only after
    provider results have been normalized into Portfolios.
    """
    pending_run = WorkflowRun.from_workflow(workflow)
    planned_steps = tuple(
        StepRun(
            step_index=step_run.step_index,
            state=StepRunState.PLANNED,
            endpoint_plans=plan_step(pending_run.step_at(step_run.step_index), graph),
        )
        for step_run in pending_run.steps
    )
    return WorkflowRun(workflow=workflow, steps=planned_steps)


__all__ = [
    "PlanningError",
    "PlanningAmbiguityError",
    "UnsupportedStepError",
    "PlanningDeferredError",
    "PlanningNotApplicableError",
    "plan_step",
    "plan_workflow",
]
