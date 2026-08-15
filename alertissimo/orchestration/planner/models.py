"""Small, execution-free value objects produced by orchestration planning."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EndpointPlan:
    """Identity of one registered endpoint selected to implement an IR step.

    Physical transport and parameter details intentionally remain in
    ``EndpointSpec`` and can be resolved later through ``EndpointRegistry``.
    """

    step_op: str
    broker: str
    origin: str
    endpoint: str
    semantic_type: str | None = None


@dataclass(frozen=True)
class ExecutionPlan:
    """Endpoint selections in the declared order of their workflow steps."""

    endpoints: tuple[EndpointPlan, ...]


__all__ = ["EndpointPlan", "ExecutionPlan"]
