"""Deterministically select physical endpoint identities for orchestration IR.

Capability validation answers *what could satisfy a step*; this planner chooses
from those viable capabilities.  It stops at endpoint identity.  A future binder
will translate generic IR arguments into physical endpoint parameters, after
which an executor may invoke the resolved ``EndpointSpec``.  None of those later
binding or execution concerns belong here.
"""

from __future__ import annotations

from alertissimo.data_layer.runtime.capability_graph import CapabilityGraph
from alertissimo.orchestration.ir.models import Source, Step, WorkflowIR
from alertissimo.orchestration.validation import (
    CapabilityValidationResult,
    SourceCapabilityResult,
    validate_step_capabilities,
)

from .models import EndpointPlan, ExecutionPlan


class PlanningError(ValueError):
    """Base class for failures to select provider endpoints."""


class PlanningAmbiguityError(PlanningError):
    """Raised when selection would require an unconfigured preference policy."""


class UnsupportedStepError(PlanningError):
    """Raised when registry capabilities cannot implement a provider-facing step."""


class PlanningDeferredError(PlanningError):
    """Raised when planning awaits capability semantics not yet modeled."""


class PlanningNotApplicableError(PlanningError):
    """Raised when a local/orchestration step does not require a provider endpoint."""


def _source_label(source: Source | None) -> str:
    if source is None:
        return "unconstrained"
    return f"{source.broker or '*'}/{source.origin or '*'}"


def _context(
    validation: CapabilityValidationResult,
    result: SourceCapabilityResult | None = None,
) -> str:
    semantic = (
        f", semantic_type={validation.semantic_type!r}"
        if validation.semantic_type is not None
        else ""
    )
    source = f", source={_source_label(result.source)}" if result else ""
    reason = result.reason if result else validation.reason
    return f"operation={validation.operation!r}{source}{semantic}: {reason}"


def _select_one(
    validation: CapabilityValidationResult,
    result: SourceCapabilityResult,
) -> EndpointPlan:
    candidates = tuple(
        sorted(
            result.candidates,
            key=lambda item: (item.broker, item.origin, item.endpoint),
        )
    )
    if len(candidates) != 1:
        identities = ", ".join(
            f"{item.broker}/{item.origin}/{item.endpoint}" for item in candidates
        )
        raise PlanningAmbiguityError(
            f"ambiguous endpoint selection for {_context(validation, result)}; "
            f"candidates=[{identities}]"
        )
    candidate = candidates[0]
    return EndpointPlan(
        step_op=validation.operation,
        broker=candidate.broker,
        origin=candidate.origin,
        endpoint=candidate.endpoint,
        semantic_type=validation.semantic_type,
    )


def plan_step(step: Step, graph: CapabilityGraph) -> tuple[EndpointPlan, ...]:
    """Select one endpoint per explicit source, or one globally if unconstrained.

    No preference is implicit: more than one viable candidate in either selection
    space is an ambiguity.  Validation statuses remain distinct so a local step is
    never mislabeled as an unsupported provider operation.
    """
    validation = validate_step_capabilities(step, graph)
    if validation.status == "not_applicable":
        raise PlanningNotApplicableError(_context(validation))
    if validation.status == "deferred":
        raise PlanningDeferredError(_context(validation))
    if validation.status == "unsupported":
        failed = next(
            (
                item
                for item in validation.source_results
                if item.status == "unsupported"
            ),
            None,
        )
        raise UnsupportedStepError(_context(validation, failed))

    # Explicit source results intentionally remain separate: selecting for one
    # requested provider must neither satisfy nor suppress another requested one.
    return tuple(
        _select_one(validation, result) for result in validation.source_results
    )


def plan_workflow(workflow: WorkflowIR, graph: CapabilityGraph) -> ExecutionPlan:
    """Compose step plans in declared order, failing on local or unplannable steps."""
    return ExecutionPlan(
        tuple(
            endpoint for step in workflow.steps for endpoint in plan_step(step, graph)
        )
    )


__all__ = [
    "PlanningAmbiguityError",
    "PlanningDeferredError",
    "PlanningError",
    "PlanningNotApplicableError",
    "UnsupportedStepError",
    "plan_step",
    "plan_workflow",
]
