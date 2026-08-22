"""Semantic-output bridge for occurrence-aligned workflow results.

Provider results normalize into object-level Portfolios. Semantic predicates that
were not safely realized as provider request constraints can then be evaluated
against those normalized records without changing their meaning.
"""

from .models import (
    ExecutionPortfolioResult,
    StepPortfolioResult,
    WorkflowPortfolioResult,
    consolidate_portfolios,
    summary_object_identity,
)
from .normalize import (
    WorkflowNormalizationAlignmentError,
    normalize_execution,
    normalize_step_execution,
    normalize_workflow_execution,
)
from .predicate import evaluate_portfolio_predicate, prune_portfolios

__all__ = [
    "ExecutionPortfolioResult",
    "StepPortfolioResult",
    "WorkflowNormalizationAlignmentError",
    "WorkflowPortfolioResult",
    "consolidate_portfolios",
    "evaluate_portfolio_predicate",
    "normalize_execution",
    "normalize_step_execution",
    "normalize_workflow_execution",
    "prune_portfolios",
    "summary_object_identity",
]
