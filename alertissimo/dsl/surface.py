"""Abstract syntax for the user-facing declarative Alertissimo DSL.

The surface model preserves what the scientist asked for without deciding how the
request will be satisfied. Formal syntax lives in ``grammar.lark``; predicate
syntax lives in ``expression.lark``. Ontology, capability validation, IR lowering,
and result-view lowering remain separate stages.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .expression import ExpressionParseError, parse_expression


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


def _predicate_text(value: str, *, context: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{context} requires a condition")
    try:
        parse_expression(value)
    except ExpressionParseError as exc:
        raise ValueError(f"{context} has invalid expression syntax: {exc}") from exc
    return value


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
    """Keep the latest N candidates after first-pass selection semantics."""

    kind: Literal["latest"] = "latest"
    count: int = Field(gt=0)


class WhereClause(SurfaceModel):
    """One general first-pass candidate predicate."""

    kind: Literal["where"] = "where"
    condition: str

    @field_validator("condition")
    @classmethod
    def require_condition(cls, value: str) -> str:
        return _predicate_text(value, context="where")


class FilterClause(SurfaceModel):
    kind: Literal["filter"] = "filter"
    condition: str

    @field_validator("condition")
    @classmethod
    def require_condition(cls, value: str) -> str:
        return _predicate_text(value, context="filter")


class RequirementClause(SurfaceModel):
    """Semantic requirement, optionally carrying one scoped predicate block.

    ``predicates`` are conjunctive conditions over the requested product. A
    predicate-bearing requirement therefore means both "ensure this semantic
    product" and "select/refine candidates using these conditions". Whether the
    provider can satisfy both in one call is a planner concern.
    """

    kind: Literal["with"] = "with"
    product: str
    source: str | None = None
    via: str | None = None
    method: str | None = None
    predicates: tuple[str, ...] = ()

    @field_validator("product")
    @classmethod
    def require_product(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("with requires a semantic product")
        return value

    @field_validator("predicates")
    @classmethod
    def require_valid_predicates(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        return tuple(
            _predicate_text(item, context="with predicate") for item in value
        )


class ConfirmClause(SurfaceModel):
    """Require an existence quorum from explicitly named independent brokers."""

    kind: Literal["confirm"] = "confirm"
    required_agreement: int = Field(ge=1)
    brokers: tuple[str, ...]

    @model_validator(mode="after")
    def validate_quorum(self) -> "ConfirmClause":
        if not self.brokers:
            raise ValueError("confirm requires at least one broker after via")
        if len(set(self.brokers)) != len(self.brokers):
            raise ValueError("confirm brokers must be unique")
        if self.required_agreement > len(self.brokers):
            raise ValueError("confirm quorum cannot exceed the broker count")
        return self


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
    """Result-view ordering; this does not create scientific workflow content."""

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
    | ConfirmClause
    | MatchClause
    | OrderByClause
    | RankedByClause,
    Field(discriminator="kind"),
]


class SurfaceScript(SurfaceModel):
    """Ordered user intent before capability resolution and WorkflowIR lowering."""

    candidates: CandidateSet
    clauses: tuple[SurfaceClause, ...] = ()

    @model_validator(mode="after")
    def validate_single_general_where_and_view_order(self) -> "SurfaceScript":
        where_count = sum(isinstance(clause, WhereClause) for clause in self.clauses)
        if where_count > 1:
            raise ValueError("only one general where clause is allowed")
        order_count = sum(isinstance(clause, OrderByClause) for clause in self.clauses)
        if order_count > 1:
            raise ValueError("only one order by clause is allowed")
        return self


def parse_surface_script(script: str) -> SurfaceScript:
    """Compatibility entry point; the production implementation is Lark-backed."""

    from .parser import parse_surface_script as parse

    return parse(script)


__all__ = [
    "AngularRadius",
    "CandidateSet",
    "ConfirmClause",
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
