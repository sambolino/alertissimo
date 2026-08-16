"""Semantic-output bridge for occurrence-aligned workflow results.

The path is ``WorkflowIR -> planner -> WorkflowRun -> binder ->
BoundEndpointCall -> runner -> ExecutionResult -> existing RecordBuilder ->
Portfolio``.  Orchestration retains workflow/Step occurrence association;
``data_layer.execution`` owns physical results, RecordBuilder owns provider
payload normalization, and Portfolio owns records and execution provenance.

Each physical execution deliberately remains an independent execution occurrence
and wrapper, and may normalize into zero, one, or many Portfolios.  Every
Portfolio represents one primary astronomical object.  Executions and Steps do
not establish cross-execution object identity; Portfolio composition and entity
resolution are intentionally out of scope.
"""

from .models import (
    ExecutionPortfolioResult,
    StepPortfolioResult,
    WorkflowPortfolioResult,
)
from .normalize import (
    WorkflowNormalizationAlignmentError,
    normalize_execution,
    normalize_step_execution,
    normalize_workflow_execution,
)

__all__ = [
    "ExecutionPortfolioResult",
    "StepPortfolioResult",
    "WorkflowNormalizationAlignmentError",
    "WorkflowPortfolioResult",
    "normalize_execution",
    "normalize_step_execution",
    "normalize_workflow_execution",
]
