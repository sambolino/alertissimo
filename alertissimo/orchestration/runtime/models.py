"""Minimal runtime state for one invocation of an orchestration workflow."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from alertissimo.orchestration.ir.models import Step, WorkflowIR


class RuntimeModel(BaseModel):
    """Serializable, strictly shaped runtime value object."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class EndpointPlan(RuntimeModel):
    """Physical identity of a registered endpoint selected by the planner.

    This contains neither the semantic Step nor transport and bound-parameter
    details.  The owning StepRun connects it to exactly one Step occurrence.
    """

    broker: str
    origin: str
    endpoint: str
    semantic_type: str | None = None


class StepRunState(StrEnum):
    """The deliberately small lifecycle vocabulary for a Step occurrence.

    ``pending`` has not been planned; ``planned`` has endpoint plans;
    ``running`` has begun execution; ``succeeded`` completed successfully; and
    ``failed`` encountered an execution failure.  Planning currently uses only
    the first two states.
    """

    PENDING = "pending"
    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class StepRun(RuntimeModel):
    """Runtime state for one semantic Step occurrence.

    Step is not StepRun: the declarative Step remains in WorkflowIR.  Two equal
    Step values may occur independently, so position identifies the occurrence
    without prematurely inventing a persistent Step ID.  This object owns all
    endpoint plans selected for that one occurrence, including provider fan-out.
    """

    step_index: int = Field(ge=0)
    state: StepRunState = StepRunState.PENDING
    endpoint_plans: tuple[EndpointPlan, ...] = ()


class WorkflowRun(RuntimeModel):
    """Runtime state for one invocation of a declarative WorkflowIR.

    WorkflowIR is intent, not runtime state.  Its ordering remains authoritative;
    this model adds one structurally aligned StepRun per declared Step.
    """

    workflow: WorkflowIR
    steps: tuple[StepRun, ...]

    @model_validator(mode="after")
    def validate_step_alignment(self) -> WorkflowRun:
        expected = list(range(len(self.workflow.steps)))
        actual = [step.step_index for step in self.steps]
        if actual != expected:
            raise ValueError(
                "StepRun indices must cover WorkflowIR steps exactly in order "
                f"(expected {expected}, got {actual})"
            )
        return self

    @classmethod
    def from_workflow(cls, workflow: WorkflowIR) -> WorkflowRun:
        """Initialize one pending StepRun for every Step, in workflow order."""

        return cls(
            workflow=workflow,
            steps=tuple(
                StepRun(step_index=index) for index in range(len(workflow.steps))
            ),
        )

    def step_at(self, index: int) -> Step:
        """Resolve a Step occurrence from its authoritative WorkflowIR."""

        return self.workflow.steps[index]

    def step_run_at(self, index: int) -> StepRun:
        """Return aligned runtime state for a workflow position."""

        return self.steps[index]


__all__ = ["EndpointPlan", "StepRun", "StepRunState", "WorkflowRun"]
