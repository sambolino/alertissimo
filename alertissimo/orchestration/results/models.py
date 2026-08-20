"""Non-scientific result-view instructions for workflow outputs.

These models describe how already-produced workflow results should be presented.
They do not alter Portfolio scientific content and are intentionally outside
``WorkflowIR``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ResultViewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResultOrderSpec(ResultViewModel):
    """Order a result view by one deterministic candidate-level scalar."""

    expression: str = Field(min_length=1)
    direction: Literal["asc", "desc"] | None = None


class ResultViewSpec(ResultViewModel):
    """Presentation instructions associated with a workflow result."""

    order_by: ResultOrderSpec | None = None


__all__ = ["ResultOrderSpec", "ResultViewSpec"]
