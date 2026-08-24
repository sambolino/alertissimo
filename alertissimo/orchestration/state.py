"""Versioned backend-owned state for resumable workflow execution."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Callable, Generic, Protocol, TypeVar
from uuid import uuid4


StateT = TypeVar("StateT")


class WorkflowStateError(ValueError):
    """A workflow-state request is invalid or cannot be satisfied safely."""


class WorkflowNotFoundError(WorkflowStateError):
    """No backend-owned workflow exists for the supplied identifier."""


class WorkflowVersionConflictError(WorkflowStateError):
    """The caller based a continuation on a stale workflow version."""


@dataclass(frozen=True)
class WorkflowSnapshot(Generic[StateT]):
    """One immutable version of a backend-owned workflow state."""

    workflow_id: str
    version: int
    result: StateT


class WorkflowStateRepository(Protocol, Generic[StateT]):
    """Storage boundary for immutable, versioned workflow snapshots."""

    def create(self, result: StateT) -> WorkflowSnapshot[StateT]: ...

    def latest(self, workflow_id: str) -> WorkflowSnapshot[StateT]: ...

    def append(
        self,
        workflow_id: str,
        *,
        expected_version: int,
        result: StateT,
    ) -> WorkflowSnapshot[StateT]: ...


def new_workflow_id() -> str:
    return f"workflow:{uuid4().hex}"


class InMemoryWorkflowStateRepository(Generic[StateT]):
    """Process-local reference repository suitable for an embedded backend.

    Only the current immutable snapshot is retained, avoiding duplicate cumulative
    results in memory. A future database implementation may retain history while
    satisfying the same repository boundary without changing orchestration code.
    """

    def __init__(
        self,
        *,
        workflow_id_factory: Callable[[], str] = new_workflow_id,
    ) -> None:
        self._workflow_id_factory = workflow_id_factory
        self._states: dict[str, WorkflowSnapshot[StateT]] = {}
        self._lock = Lock()

    def create(self, result: StateT) -> WorkflowSnapshot[StateT]:
        with self._lock:
            workflow_id = self._workflow_id_factory()
            while not workflow_id or workflow_id in self._states:
                workflow_id = self._workflow_id_factory()
            snapshot = WorkflowSnapshot(
                workflow_id=workflow_id,
                version=1,
                result=result,
            )
            self._states[workflow_id] = snapshot
            return snapshot

    def latest(self, workflow_id: str) -> WorkflowSnapshot[StateT]:
        with self._lock:
            try:
                return self._states[workflow_id]
            except KeyError as error:
                raise WorkflowNotFoundError(
                    f"unknown workflow_id: {workflow_id!r}"
                ) from error

    def append(
        self,
        workflow_id: str,
        *,
        expected_version: int,
        result: StateT,
    ) -> WorkflowSnapshot[StateT]:
        with self._lock:
            try:
                current = self._states[workflow_id]
            except KeyError as error:
                raise WorkflowNotFoundError(
                    f"unknown workflow_id: {workflow_id!r}"
                ) from error
            if current.version != expected_version:
                raise WorkflowVersionConflictError(
                    f"workflow {workflow_id!r} is at version {current.version}, "
                    f"not requested base_version {expected_version}"
                )
            snapshot = WorkflowSnapshot(
                workflow_id=workflow_id,
                version=current.version + 1,
                result=result,
            )
            self._states[workflow_id] = snapshot
            return snapshot


__all__ = [
    "InMemoryWorkflowStateRepository",
    "WorkflowNotFoundError",
    "WorkflowSnapshot",
    "WorkflowStateError",
    "WorkflowStateRepository",
    "WorkflowVersionConflictError",
    "new_workflow_id",
]
