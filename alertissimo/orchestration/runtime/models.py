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


class CandidateInputRef(RuntimeModel):
    """Reference to an earlier semantic Step whose output defines candidate input.

    On an :class:`EndpointPlan` this supplies runtime target identities for a new
    physical call. On a local candidate-transforming :class:`StepRun` it identifies
    the earlier normalized semantic view that the local Step consumes. Neither use
    mutates WorkflowIR or implies physical execution reuse.
    """

    step_index: int = Field(ge=0)


class EndpointPlan(RuntimeModel):
    """Physical identity selected for one semantic Step occurrence.

    ``required`` distinguishes physical calls that are necessary to satisfy the
    semantic Step from supplementary calls that improve completeness but may fail
    without failing the Step. The planner owns that distinction; the executor never
    infers optionality from endpoint names or provider behavior.

    ``execution_reuse_from`` records that this semantic plan is satisfied by an
    earlier physical execution. ``candidate_input_from`` records a distinct case:
    this plan owns a new invocation whose runtime target values come from an
    earlier semantic candidate set. Neither relation changes or collapses
    WorkflowIR Steps.
    """

    broker: str
    origin: str
    endpoint: str
    semantic_type: str | None = None
    predicate_realization: PredicateRealization | None = None
    execution_reuse_from: EndpointPlanRef | None = None
    candidate_input_from: CandidateInputRef | None = None
    required: bool = True

    @model_validator(mode="after")
    def require_one_dependency_mode(self) -> "EndpointPlan":
        if self.execution_reuse_from is not None and self.candidate_input_from is not None:
            raise ValueError(
                "endpoint plan cannot both reuse an execution and bind from candidate output"
            )
        return self


class StepRunState(StrEnum):
    """The deliberately small lifecycle vocabulary for a Step occurrence."""

    PENDING = "pending"
    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class StepRun(RuntimeModel):
    """Runtime state for one semantic Step occurrence.

    ``execution_plan_indexes`` aligns successful physical results in
    ``execution_ids`` with the endpoint-plan indexes that produced them. It is
    normally ``0..N-1``; sparse indexes occur when supplementary plans fail or
    candidate-dependent plans are vacuous while other plans still execute.

    ``vacuous_plan_indexes`` records candidate-dependent physical plans that were
    deliberately not invoked because their referenced runtime candidate partition
    was empty. This is distinct from endpoint failure or supplementary omission and
    lets normalization prove why a required physical plan legitimately has no
    execution result.
    """

    step_index: int = Field(ge=0)
    state: StepRunState = StepRunState.PENDING
    endpoint_plans: tuple[EndpointPlan, ...] = ()
    candidate_input_from: CandidateInputRef | None = None
    execution_ids: tuple[str, ...] = ()
    execution_plan_indexes: tuple[int, ...] = ()
    vacuous_plan_indexes: tuple[int, ...] = ()
    warnings: tuple[str, ...] = ()
    error: str | None = None

    @model_validator(mode="after")
    def validate_execution_alignment_metadata(self) -> "StepRun":
        if self.execution_plan_indexes:
            if len(self.execution_plan_indexes) != len(self.execution_ids):
                raise ValueError(
                    "execution_plan_indexes must align one-to-one with execution_ids"
                )
            if len(set(self.execution_plan_indexes)) != len(self.execution_plan_indexes):
                raise ValueError("execution_plan_indexes must not contain duplicates")
            if tuple(sorted(self.execution_plan_indexes)) != self.execution_plan_indexes:
                raise ValueError("execution_plan_indexes must be in endpoint-plan order")
            if any(index >= len(self.endpoint_plans) for index in self.execution_plan_indexes):
                raise ValueError("execution_plan_indexes reference unknown endpoint plans")

        if self.vacuous_plan_indexes:
            if len(set(self.vacuous_plan_indexes)) != len(self.vacuous_plan_indexes):
                raise ValueError("vacuous_plan_indexes must not contain duplicates")
            if tuple(sorted(self.vacuous_plan_indexes)) != self.vacuous_plan_indexes:
                raise ValueError("vacuous_plan_indexes must be in endpoint-plan order")
            if any(index >= len(self.endpoint_plans) for index in self.vacuous_plan_indexes):
                raise ValueError("vacuous_plan_indexes reference unknown endpoint plans")
            if set(self.execution_plan_indexes) & set(self.vacuous_plan_indexes):
                raise ValueError(
                    "endpoint plan cannot be both executed and vacuous"
                )
            if any(
                self.endpoint_plans[index].candidate_input_from is None
                for index in self.vacuous_plan_indexes
            ):
                raise ValueError(
                    "vacuous_plan_indexes may reference only candidate-dependent endpoint plans"
                )

        return self


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
            local_candidate_reference = step_run.candidate_input_from
            if local_candidate_reference is not None:
                if local_candidate_reference.step_index >= step_run.step_index:
                    raise ValueError(
                        "local candidate input must reference an earlier Step occurrence "
                        f"(step_index {step_run.step_index}, reference step_index "
                        f"{local_candidate_reference.step_index})"
                    )
                if local_candidate_reference.step_index >= len(self.steps):
                    raise ValueError(
                        "local candidate input references unknown Step occurrence"
                    )

            for plan_index, plan in enumerate(step_run.endpoint_plans):
                reference = plan.execution_reuse_from
                if reference is not None:
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

                candidate_reference = plan.candidate_input_from
                if candidate_reference is not None:
                    if candidate_reference.step_index >= step_run.step_index:
                        raise ValueError(
                            "candidate input must reference an earlier Step occurrence "
                            f"(step_index {step_run.step_index}, plan_index {plan_index}, "
                            f"reference step_index {candidate_reference.step_index})"
                        )
                    if candidate_reference.step_index >= len(self.steps):
                        raise ValueError(
                            "candidate input references unknown Step occurrence"
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
    "CandidateInputRef",
    "EndpointPlan",
    "EndpointPlanRef",
    "PredicateRealization",
    "StepRun",
    "StepRunState",
    "WorkflowRun",
]
