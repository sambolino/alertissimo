"""Immutable endpoint-selection results produced by orchestration planning."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EndpointPlan:
    """Identity of one registered endpoint selected to implement an IR step.

    Physical transport details and parameter schemas remain owned by
    ``EndpointSpec`` and are deliberately not copied into this model.
    """

    step_op: str
    broker: str
    origin: str
    endpoint: str
    semantic_type: str | None = None


@dataclass(frozen=True)
class ExecutionPlan:
    """Ordered endpoint selections for an entirely provider-facing workflow."""

    endpoint_plans: tuple[EndpointPlan, ...]


__all__ = ["EndpointPlan", "ExecutionPlan"]
