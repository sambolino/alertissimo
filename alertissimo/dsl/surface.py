"""Abstract syntax for the user-facing declarative Alertissimo DSL.

The surface model preserves what the scientist asked for without deciding how the
request will be satisfied. Formal syntax lives in ``grammar.lark``; ontology and
capability validation are separate later stages.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SurfaceModel(BaseModel):
    """Strict immutable value object in the user-facing DSL surface."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DSLParseError(ValueError):
    """Formal-syntax or structural DSL error with optional source location."""

    def __init__(
        self,
        message: str,
        *,
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        self.message = message
        self.line = line
        self.column = column
        location = ""
        if line is not None:
            location = f"Line {line}"
            if column is not None:
                location += f", column {column}"
            location += ": "
        super().__init__(location + message)


class CandidateSet(SurfaceModel):
    """Initial object population; these candidate origins remain fixed."""

    kind: Literal["objects"] = "objects"
    origins: tuple[str, ...]
    broker: str | None = None

    @field_validator("origins")
    @classmethod
    def require_unique_origins(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("at least one candidate origin is required")
        if len(set(value)) != len(value):
            raise ValueError("candidate origins must be unique")
        return value


class AngularRadius(SurfaceModel):
    value: float = Field(gt=0)
    unit: Literal["deg", "arcmin", "arcsec"] | None = None


class InsideClause(SurfaceModel):
    kind: Literal["inside"] = "inside"
    ra: float = Field(ge=0, lt=360)
    dec: float = Field(ge=-90, le=90)
    radius: AngularRadius


class Duration(SurfaceModel):
    value: float = Field(gt=0)
    unit: Literal["s", "min", "h", "d", "w"]


class WithinClause(SurfaceModel):
    """Time window; a one-value form is a lookback ending at runtime ``now``."""

    kind: Literal["within"] = "within"
    duration: Duration | None = None
    start: str | None = None
    end: str | None = None
    relative_to: Literal["now"] | None = None

    @model_validator(mode="after")
    def require_one_window_form(self) -> "WithinClause":
        relative = self.duration is not None
        explicit = self.start is not None or self.end is not None
        if relative == explicit:
            raise ValueError(
                "within must be either a duration or an explicit start/end window"
            )
        if relative and self.relative_to != "now":
            raise ValueError("single-value within is relative to now")
        if explicit and (self.start is None or self.end is None):
            raise ValueError("explicit within requires both start and end")
        if explicit and self.relative_to is not None:
            raise ValueError("explicit within cannot also be relative to now")
        return self


class LatestClause(SurfaceModel):
    kind: Literal["latest"] = "latest"
    count: int = Field(gt=0)


class WhereClause(SurfaceModel):
    kind: Literal["where"] = "where"
    condition: str

    @field_validator("condition")
    @classmethod
    def require_condition(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("where requires a condition")
        return value


class FilterClause(SurfaceModel):
    kind: Literal["filter"] = "filter"
    condition: str

    @field_validator("condition")
    @classmethod
    def require_condition(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("filter requires a condition")
        return value


class RequirementClause(SurfaceModel):
    """Semantic enrichment requirement; it never filters candidates by itself."""

    kind: Literal["with"] = "with"
    product: str
    source: str | None = None
    via: str | None = None
    method: str | None = None

    @field_validator("product")
    @classmethod
    def require_product(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("with requires a semantic product")
        return value


class MatchClause(SurfaceModel):
    """Association request; counterpart origins never mutate candidate origins."""

    kind: Literal["match"] = "match"
    counterpart_origin: str | None = None
    via: str | None = None
    within: Duration | None = None
    on: str | None = None

    @model_validator(mode="after")
    def require_counterpart_or_predicate(self) -> "MatchClause":
        if self.counterpart_origin is None and self.on is None:
            raise ValueError("match requires a counterpart origin or an 'on' predicate")
        return self


class OrderByClause(SurfaceModel):
    kind: Literal["order_by"] = "order_by"
    expression: str
    direction: Literal["asc", "desc"] | None = None


class RankedByClause(SurfaceModel):
    kind: Literal["ranked_by"] = "ranked_by"
    criterion: str
    direction: Literal["asc", "desc"] | None = None


SurfaceClause = Annotated[
    InsideClause
    | WithinClause
    | LatestClause
    | WhereClause
    | FilterClause
    | RequirementClause
    | MatchClause
    | OrderByClause
    | RankedByClause,
    Field(discriminator="kind"),
]


class SurfaceScript(SurfaceModel):
    """Ordered user intent before capability resolution and WorkflowIR lowering."""

    candidates: CandidateSet
    clauses: tuple[SurfaceClause, ...] = ()


def parse_surface_script(script: str) -> SurfaceScript:
    """Compatibility entry point; the production implementation is Lark-backed."""

    from .parser import parse_surface_script as parse

    return parse(script)


__all__ = [
    "AngularRadius",
    "CandidateSet",
    "DSLParseError",
    "Duration",
    "FilterClause",
    "InsideClause",
    "LatestClause",
    "MatchClause",
    "OrderByClause",
    "RankedByClause",
    "RequirementClause",
    "SurfaceClause",
    "SurfaceScript",
    "WhereClause",
    "WithinClause",
    "parse_surface_script",
]
