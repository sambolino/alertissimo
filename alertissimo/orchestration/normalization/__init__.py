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
from .selection import (
    SearchSelectionError,
    select_portfolios,
    select_step_portfolios,
)

__all__ = [
    "ExecutionPortfolioResult",
    "StepPortfolioResult",
    "SearchSelectionError",
    "WorkflowNormalizationAlignmentError",
    "WorkflowPortfolioResult",
    "consolidate_portfolios",
    "evaluate_portfolio_predicate",
    "normalize_execution",
    "normalize_step_execution",
    "normalize_workflow_execution",
    "prune_portfolios",
    "select_portfolios",
    "select_step_portfolios",
    "summary_object_identity",
]
