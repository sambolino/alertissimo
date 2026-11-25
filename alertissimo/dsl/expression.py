"""Formal scientific-predicate AST and parser for the declarative DSL."""

from __future__ import annotations

from ast import literal_eval
from functools import lru_cache
from importlib.resources import files
from typing import Annotated, Literal, TypeAlias
import math

from lark import Lark, Token, Transformer, UnexpectedInput
from lark.exceptions import VisitError
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExpressionModel(BaseModel):
    """Strict immutable node in the scientific predicate expression AST."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ExpressionParseError(ValueError):
    """Formal expression-syntax error with location relative to the expression."""

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


class ReferenceExpression(ExpressionModel):
    """Semantic/path reference before or after ontology scope resolution."""

    kind: Literal["reference"] = "reference"
    root: str
    path: tuple[str, ...] = ()
    producer: str | None = None
    channel: str | None = None
    record_type: str | None = None
    resolution: Literal["unresolved", "absolute", "scoped"] = "unresolved"

    @property
    def field_path(self) -> str:
        return ".".join(self.path)

    @property
    def semantic_record_type(self) -> str | None:
        if self.record_type is None:
            return None
        value = self.record_type
        if self.producer is not None:
            value += f"@{self.producer}"
            if self.channel is not None:
                value += f":{self.channel}"
        return value


class LiteralExpression(ExpressionModel):
    kind: Literal["literal"] = "literal"
    value: str | int | float | bool


class AggregateExpression(ExpressionModel):
    kind: Literal["aggregate"] = "aggregate"
    function: Literal["count", "min", "max"]
    reference: ReferenceExpression
    condition: "Expression | None" = None

    @model_validator(mode="after")
    def count_condition_only(self):
        if self.condition is not None and self.function != "count":
            raise ValueError("only count accepts an element condition")
        return self


OperandExpression: TypeAlias = Annotated[
    ReferenceExpression | LiteralExpression | AggregateExpression,
    Field(discriminator="kind"),
]


class ComparisonExpression(ExpressionModel):
    kind: Literal["comparison"] = "comparison"
    operator: Literal["=", "!=", "<", "<=", ">", ">="]
    left: OperandExpression
    right: OperandExpression

    @model_validator(mode="after")
    def numeric_aggregate_comparison(self):
        for aggregate, other in ((self.left, self.right), (self.right, self.left)):
            if isinstance(aggregate, AggregateExpression) and not (
                isinstance(other, LiteralExpression)
                and (type(other.value) is int or type(other.value) is float and math.isfinite(other.value))
            ):
                raise ValueError("an aggregate must be compared with a finite numeric literal")
        return self


class BooleanExpression(ExpressionModel):
    kind: Literal["boolean"] = "boolean"
    operator: Literal["and", "or"]
    operands: tuple["Expression", ...]

    @model_validator(mode="after")
    def require_multiple_operands(self) -> "BooleanExpression":
        if len(self.operands) < 2:
            raise ValueError("boolean expression requires at least two operands")
        return self


class NotExpression(ExpressionModel):
    kind: Literal["not"] = "not"
    operand: "Expression"


class ExistsExpression(ExpressionModel):
    kind: Literal["exists"] = "exists"
    operand: ReferenceExpression


class QuantifierExpression(ExpressionModel):
    kind: Literal["quantifier"] = "quantifier"
    quantifier: Literal["any", "every"]
    parameter: Literal["filter", "output"]
    values: tuple[str, ...] | None = None
    operand: "Expression"

    @model_validator(mode="after")
    def explicit_domain(self):
        if self.values is not None and (not self.values or len(set(self.values)) != len(self.values)):
            raise ValueError("quantifier values must be nonempty and duplicate-free")
        return self


Expression: TypeAlias = Annotated[
    ComparisonExpression | BooleanExpression | NotExpression | ExistsExpression | QuantifierExpression,
    Field(discriminator="kind"),
]

AggregateExpression.model_rebuild()
ComparisonExpression.model_rebuild()
BooleanExpression.model_rebuild()
NotExpression.model_rebuild()
QuantifierExpression.model_rebuild()


def expression_grammar_text() -> str:
    """Return the hand-authored predicate grammar used by the production parser."""

    return files("alertissimo.dsl").joinpath("expression.lark").read_text(
        encoding="utf-8"
    )


@lru_cache(maxsize=1)
def _expression_parser() -> Lark:
    return Lark(
        expression_grammar_text(),
        parser="lalr",
        lexer="contextual",
        propagate_positions=True,
    )


def _reference(raw: str) -> ReferenceExpression:
    head, *path = raw.split(".")
    root, at, qualifiers = head.partition("@")
    producer: str | None = None
    channel: str | None = None
    if at:
        producer, colon, channel_value = qualifiers.partition(":")
        if colon:
            channel = channel_value or None
    return ReferenceExpression(
        root=root.lower(),
        path=tuple(item.lower() for item in path),
        producer=producer.lower() if producer else None,
        channel=channel.lower() if channel else None,
    )


class _ExpressionTransformer(Transformer):
    def start(self, items):
        return items[0]

    def reference(self, items):
        return _reference(str(items[0]))

    def string(self, items):
        return LiteralExpression(value=literal_eval(str(items[0])))

    def number(self, items):
        raw = str(items[0])
        value = (
            float(raw)
            if any(marker in raw.lower() for marker in (".", "e"))
            else int(raw)
        )
        return LiteralExpression(value=value)

    def true(self, _items):
        return LiteralExpression(value=True)

    def false(self, _items):
        return LiteralExpression(value=False)

    def comparison(self, items):
        return ComparisonExpression(
            left=items[0],
            operator=str(items[1]),
            right=items[2],
        )

    def count_aggregate(self, items):
        reference = next(item for item in items if isinstance(item, ReferenceExpression))
        condition = next((item for item in items if isinstance(item, ExpressionModel)
                          and not isinstance(item, ReferenceExpression)), None)
        return AggregateExpression(function="count", reference=reference, condition=condition)

    def min_aggregate(self, items):
        return AggregateExpression(function="min", reference=next(
            item for item in items if isinstance(item, ReferenceExpression)))

    def max_aggregate(self, items):
        return AggregateExpression(function="max", reference=next(
            item for item in items if isinstance(item, ReferenceExpression)))

    def any_kind(self, _items):
        return "any"

    def every_kind(self, _items):
        return "every"

    def domain_restriction(self, items):
        return tuple(str(item) for item in items if item is not None)

    def quantifier(self, items):
        parameter = next(item for item in items if isinstance(item, Token) and item.type == "PARAMETER")
        quantifier = next(item for item in items if type(item) is str)
        values = next((item for item in items if isinstance(item, tuple)), None)
        operand = next(item for item in items if isinstance(item, ExpressionModel))
        return QuantifierExpression(quantifier=quantifier, parameter=str(parameter)[1:-1],
                                    values=values, operand=operand)

    def grouped(self, items):
        return items[0]

    def not_expr(self, items):
        operand = next(item for item in items if not isinstance(item, Token))
        return NotExpression(operand=operand)

    def and_expr(self, items):
        operands = tuple(item for item in items if not isinstance(item, Token))
        if len(operands) == 1:
            return operands[0]
        return BooleanExpression(operator="and", operands=operands)

    def or_expr(self, items):
        operands = tuple(item for item in items if not isinstance(item, Token))
        if len(operands) == 1:
            return operands[0]
        return BooleanExpression(operator="or", operands=operands)

    def exists_prefix(self, items):
        operand = next(
            item for item in items if isinstance(item, ReferenceExpression)
        )
        return ExistsExpression(operand=operand)

    def exists_suffix(self, items):
        operand = next(
            item for item in items if isinstance(item, ReferenceExpression)
        )
        return ExistsExpression(operand=operand)


_TRANSFORMER = _ExpressionTransformer()


def parse_expression(text: str) -> Expression:
    """Parse one predicate expression without resolving ontology semantics."""

    value = text.strip()
    if not value:
        raise ExpressionParseError("expression cannot be empty")
    try:
        result = _TRANSFORMER.transform(_expression_parser().parse(value))
    except UnexpectedInput as exc:
        raise ExpressionParseError(
            "invalid expression syntax",
            line=getattr(exc, "line", None),
            column=getattr(exc, "column", None),
        ) from exc
    except VisitError as exc:
        raise ExpressionParseError(str(exc.orig_exc)) from exc
    except (ValueError, SyntaxError) as exc:
        raise ExpressionParseError(str(exc)) from exc

    if not isinstance(
        result,
        (ComparisonExpression, BooleanExpression, NotExpression, ExistsExpression, QuantifierExpression),
    ):
        raise ExpressionParseError("parser did not produce a predicate expression")
    return result


def iter_references(expression: ExpressionModel, _collection: ReferenceExpression | None = None):
    """Yield material references; element leaves inherit their aggregate's root."""
    if isinstance(expression, ReferenceExpression):
        if _collection is None:
            yield expression
        else:
            yield _collection.model_copy(update={
                "path": (*_collection.path, expression.root, *expression.path),
            })
    elif isinstance(expression, AggregateExpression):
        yield expression.reference
        if expression.condition is not None:
            yield from iter_references(expression.condition, expression.reference)
    elif isinstance(expression, ComparisonExpression):
        yield from iter_references(expression.left, _collection)
        yield from iter_references(expression.right, _collection)
    elif isinstance(expression, BooleanExpression):
        for operand in expression.operands:
            yield from iter_references(operand, _collection)
    elif isinstance(expression, (NotExpression, QuantifierExpression)):
        yield from iter_references(expression.operand, _collection)
    elif isinstance(expression, ExistsExpression):
        yield from iter_references(expression.operand, _collection)


def contains_collection_expression(expression: ExpressionModel) -> bool:
    if isinstance(expression, (AggregateExpression, QuantifierExpression)):
        return True
    if isinstance(expression, ComparisonExpression):
        return any(contains_collection_expression(item) for item in (expression.left, expression.right))
    if isinstance(expression, BooleanExpression):
        return any(contains_collection_expression(item) for item in expression.operands)
    if isinstance(expression, NotExpression):
        return contains_collection_expression(expression.operand)
    return False


def map_references(expression: ExpressionModel, mapper):
    """Map every syntactic reference, preserving aggregate and quantifier scope."""
    if isinstance(expression, ReferenceExpression):
        return mapper(expression)
    if isinstance(expression, LiteralExpression):
        return expression
    if isinstance(expression, AggregateExpression):
        return expression.model_copy(update={
            "reference": mapper(expression.reference),
            "condition": (map_references(expression.condition, mapper)
                          if expression.condition is not None else None),
        })
    if isinstance(expression, ComparisonExpression):
        return expression.model_copy(update={"left": map_references(expression.left, mapper),
                                             "right": map_references(expression.right, mapper)})
    if isinstance(expression, BooleanExpression):
        return expression.model_copy(update={"operands": tuple(map_references(item, mapper)
                                                               for item in expression.operands)})
    if isinstance(expression, (NotExpression, QuantifierExpression)):
        return expression.model_copy(update={"operand": map_references(expression.operand, mapper)})
    if isinstance(expression, ExistsExpression):
        return expression.model_copy(update={"operand": mapper(expression.operand)})
    raise TypeError(f"unsupported expression node: {type(expression).__name__}")


__all__ = [
    "AggregateExpression", "QuantifierExpression", "contains_collection_expression",
    "BooleanExpression",
    "ComparisonExpression",
    "ExistsExpression",
    "Expression",
    "ExpressionModel",
    "ExpressionParseError",
    "LiteralExpression",
    "NotExpression",
    "OperandExpression",
    "ReferenceExpression",
    "expression_grammar_text",
    "iter_references",
    "map_references",
    "parse_expression",
]
