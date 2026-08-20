"""Minimal runtime state for one invocation of an orchestration workflow."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from alertissimo.orchestration.ir.models import Step, WorkflowIR
from alertissimo.orchestration.ir.predicates import Predicate


class RuntimeModel(BaseModel):
    """Common configuration for immutable runtime value objects."""

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


class EndpointPlanRef(RuntimeModel):
    """Reference to one earlier physical endpoint plan in the same WorkflowRun."""

    step_index: int = Field(ge=0)
    plan_index: int = Field(ge=0)


class EndpointPlan(RuntimeModel):
    """Physical identity selected for one semantic Step occurrence.

    ``execution_reuse_from`` records that this semantic plan is satisfied by an
    earlier physical execution. It never changes or collapses WorkflowIR Steps.
    """

    broker: str
    origin: str
    endpoint: str
    semantic_type: str | None = None
    predicate_realization: PredicateRealization | None = None
    execution_reuse_from: EndpointPlanRef | None = None


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
        for step_run in self.steps:
            for plan_index, plan in enumerate(step_run.endpoint_plans):
                reference = plan.execution_reuse_from
                if reference is None:
                    continue
                if reference.step_index >= step_run.step_index:
                    raise ValueError(
                        "execution reuse must reference an earlier Step occurrence "
                        f"(step_index {step_run.step_index}, plan_index {plan_index}, "
                        f"reference step_index {reference.step_index})"
                    )
                if reference.step_index >= len(self.steps):
                    raise ValueError("execution reuse references unknown Step occurrence")
                owner = self.steps[reference.step_index]
                if reference.plan_index >= len(owner.endpoint_plans):
                    raise ValueError(
                        "execution reuse references unknown endpoint plan "
                        f"({reference.step_index}, {reference.plan_index})"
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
    "EndpointPlanRef",
    "PredicateRealization",
    "StepRun",
    "StepRunState",
    "WorkflowRun",
]
