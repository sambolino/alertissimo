"""Minimal runtime state for one invocation of an orchestration workflow."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from alertissimo.orchestration.ir.models import Step, WorkflowIR
from alertissimo.orchestration.ir.predicates import Predicate


class RuntimeModel(BaseModel):
    """Serializable, strictly shaped runtime value object."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PredicateRealization(RuntimeModel):
    """How one endpoint will satisfy one semantic predicate.

    ``pushdown`` and ``residual`` remain semantic predicates. ``params`` contains
    only the physical request values proven equivalent to ``pushdown`` by the
    provider's request mappings. Residual evaluation happens after normalization.
    """

    pushdown: Predicate | None = None
    residual: Predicate | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_predicate_content(self) -> "PredicateRealization":
        if self.pushdown is None and self.residual is None:
            raise ValueError("predicate realization requires pushdown or residual content")
        if self.pushdown is None and self.params:
            raise ValueError("physical predicate params require semantic pushdown evidence")
        return self


class EndpointPlan(RuntimeModel):
    """Physical identity of a registered endpoint selected by the planner.

    Predicate realization is execution strategy, not scientific intent: the
    authoritative semantic predicate remains on the owning IR Step.
    """

    broker: str
    origin: str
    endpoint: str
    semantic_type: str | None = None
    predicate_realization: PredicateRealization | None = None


class StepRunState(StrEnum):
    """The deliberately small lifecycle vocabulary for a Step occurrence."""

    PENDING = "pending"
    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class StepRun(RuntimeModel):
    """Runtime state for one semantic Step occurrence."""

    step_index: int = Field(ge=0)
    state: StepRunState = StepRunState.PENDING
    endpoint_plans: tuple[EndpointPlan, ...] = ()
    execution_ids: tuple[str, ...] = ()
    error: str | None = None


class WorkflowRun(RuntimeModel):
    """Runtime state for one invocation of a declarative WorkflowIR."""

    workflow: WorkflowIR
    steps: tuple[StepRun, ...]

    @model_validator(mode="after")
    def validate_step_alignment(self) -> "WorkflowRun":
        expected = list(range(len(self.workflow.steps)))
        actual = [step.step_index for step in self.steps]
        if actual != expected:
            raise ValueError(
                "StepRun indices must cover WorkflowIR steps exactly in order "
                f"(expected {expected}, got {actual})"
            )
        return self

    @classmethod
    def from_workflow(cls, workflow: WorkflowIR) -> "WorkflowRun":
        return cls(
            workflow=workflow,
            steps=tuple(
                StepRun(step_index=index) for index in range(len(workflow.steps))
            ),
        )

    def step_at(self, index: int) -> Step:
        return self.workflow.steps[index]

    def step_run_at(self, index: int) -> StepRun:
        return self.steps[index]


__all__ = [
    "EndpointPlan",
    "PredicateRealization",
    "StepRun",
    "StepRunState",
    "WorkflowRun",
]
