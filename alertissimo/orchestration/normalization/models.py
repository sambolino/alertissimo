"""Immutable workflow-occurrence wrappers around normalized portfolios."""

from __future__ import annotations

from dataclasses import dataclass

from alertissimo.data_layer.representations import Portfolio
from alertissimo.orchestration.runtime import WorkflowRun


@dataclass(frozen=True)
class ExecutionPortfolioResult:
    """Zero or more object Portfolios produced by one physical execution."""

    execution_id: str
    portfolios: tuple[Portfolio, ...]


@dataclass(frozen=True)
class StepPortfolioResult:
    """Normalized physical executions for one workflow Step occurrence."""

    step_index: int
    executions: tuple[ExecutionPortfolioResult, ...]


@dataclass(frozen=True)
class WorkflowPortfolioResult:
    """A WorkflowRun and its occurrence-aligned normalized output."""

    run: WorkflowRun
    steps: tuple[StepPortfolioResult, ...]


__all__ = [
    "ExecutionPortfolioResult",
    "StepPortfolioResult",
    "WorkflowPortfolioResult",
]
