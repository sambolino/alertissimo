"""Provider-independent semantic predicates used by orchestration IR.

These models are the canonical middle-layer representation of filtering intent.
They refer only to ontology record families/fields plus semantic qualifiers; they
never name provider endpoints or physical request parameters.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


NonEmptyStr = Annotated[str, Field(min_length=1, pattern=r".*\S.*")]


class PredicateModel(BaseModel):
    """Strict immutable base for semantic predicate nodes."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SemanticReference(PredicateModel):
    """One ontology reference, optionally qualified by producer/channel.

    ``semantic_type`` is the ontology record family (for example
    ``classification``). ``field_path`` is relative to that record. Empty
    ``field_path`` is allowed only for existence tests over the record family.
    """

    semantic_type: NonEmptyStr
    field_path: str = ""
    producer: NonEmptyStr | None = None
    channel: NonEmptyStr | None = None

    @field_validator("field_path")
    @classmethod
    def normalize_field_path(cls, value: str) -> str:
        value = value.strip().strip(".")
        if "@" in value:
            raise ValueError("field_path must be relative to its semantic record")
        return value

    @property
    def ontology_path(self) -> str:
        return self.semantic_type + (f".{self.field_path}" if self.field_path else "")

    @property
    def qualified_record_type(self) -> str:
        value = self.semantic_type
        if self.producer is not None:
            value += f"@{self.producer}"
            if self.channel is not None:
                value += f":{self.channel}"
        elif self.channel is not None:
            # Channel without producer is not part of the current record syntax,
            # but retaining it explicitly avoids silently discarding user intent.
            value += f"@*:{self.channel}"
        return value


class PredicateLiteral(PredicateModel):
    kind: Literal["literal"] = "literal"
    value: str | int | float | bool


class ComparisonPredicate(PredicateModel):
    kind: Literal["comparison"] = "comparison"
    operator: Literal["=", "!=", "<", "<=", ">", ">="]
    reference: SemanticReference
    value: PredicateLiteral


class ExistsPredicate(PredicateModel):
    kind: Literal["exists"] = "exists"
    reference: SemanticReference


class NotPredicate(PredicateModel):
    kind: Literal["not"] = "not"
    operand: "Predicate"


class BooleanPredicate(PredicateModel):
    kind: Literal["boolean"] = "boolean"
    operator: Literal["and", "or"]
    operands: tuple["Predicate", ...]

    @model_validator(mode="after")
    def require_multiple_operands(self) -> "BooleanPredicate":
        if len(self.operands) < 2:
            raise ValueError("boolean predicate requires at least two operands")
        return self


Predicate: TypeAlias = Annotated[
    ComparisonPredicate | BooleanPredicate | NotPredicate | ExistsPredicate,
    Field(discriminator="kind"),
]

NotPredicate.model_rebuild()
BooleanPredicate.model_rebuild()


def and_predicates(predicates: list[Predicate] | tuple[Predicate, ...]) -> Predicate | None:
    """Conjoin predicates without manufacturing a one-child boolean node."""

    items = tuple(predicate for predicate in predicates if predicate is not None)
    if not items:
        return None
    if len(items) == 1:
        return items[0]
    return BooleanPredicate(operator="and", operands=items)


def iter_semantic_references(predicate: Predicate):
    """Yield ontology references in stable predicate order."""

    if isinstance(predicate, ComparisonPredicate):
        yield predicate.reference
    elif isinstance(predicate, ExistsPredicate):
        yield predicate.reference
    elif isinstance(predicate, NotPredicate):
        yield from iter_semantic_references(predicate.operand)
    elif isinstance(predicate, BooleanPredicate):
        for operand in predicate.operands:
            yield from iter_semantic_references(operand)


__all__ = [
    "BooleanPredicate",
    "ComparisonPredicate",
    "ExistsPredicate",
    "NotPredicate",
    "Predicate",
    "PredicateLiteral",
    "PredicateModel",
    "SemanticReference",
    "and_predicates",
    "iter_semantic_references",
]
