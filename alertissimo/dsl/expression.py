"""Formal scientific-predicate AST and parser for the declarative DSL."""

from __future__ import annotations

from ast import literal_eval
from functools import lru_cache
from importlib.resources import files
from typing import Literal, TypeAlias

from lark import Lark, Token, Transformer, UnexpectedInput
from pydantic import BaseModel, ConfigDict, SerializeAsAny, model_validator


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


OperandExpression: TypeAlias = ReferenceExpression | LiteralExpression


class ComparisonExpression(ExpressionModel):
    kind: Literal["comparison"] = "comparison"
    operator: Literal["=", "!=", "<", "<=", ">", ">="]
    left: OperandExpression
    right: OperandExpression


class BooleanExpression(ExpressionModel):
    kind: Literal["boolean"] = "boolean"
    operator: Literal["and", "or"]
    operands: tuple[SerializeAsAny[ExpressionModel], ...]

    @model_validator(mode="after")
    def require_multiple_operands(self) -> "BooleanExpression":
        if len(self.operands) < 2:
            raise ValueError("boolean expression requires at least two operands")
        return self


class NotExpression(ExpressionModel):
    kind: Literal["not"] = "not"
    operand: SerializeAsAny[ExpressionModel]


class ExistsExpression(ExpressionModel):
    kind: Literal["exists"] = "exists"
    operand: ReferenceExpression


Expression: TypeAlias = (
    ComparisonExpression | BooleanExpression | NotExpression | ExistsExpression
)


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
    except (ValueError, SyntaxError) as exc:
        raise ExpressionParseError(str(exc)) from exc

    if not isinstance(
        result,
        (ComparisonExpression, BooleanExpression, NotExpression, ExistsExpression),
    ):
        raise ExpressionParseError("parser did not produce a predicate expression")
    return result


def iter_references(expression: ExpressionModel):
    """Yield reference nodes in stable source order."""

    if isinstance(expression, ComparisonExpression):
        if isinstance(expression.left, ReferenceExpression):
            yield expression.left
        if isinstance(expression.right, ReferenceExpression):
            yield expression.right
    elif isinstance(expression, BooleanExpression):
        for operand in expression.operands:
            yield from iter_references(operand)
    elif isinstance(expression, NotExpression):
        yield from iter_references(expression.operand)
    elif isinstance(expression, ExistsExpression):
        yield expression.operand


def map_references(expression: ExpressionModel, mapper):
    """Return an expression copy with ``mapper`` applied to every reference node."""

    if isinstance(expression, ComparisonExpression):
        left = (
            mapper(expression.left)
            if isinstance(expression.left, ReferenceExpression)
            else expression.left
        )
        right = (
            mapper(expression.right)
            if isinstance(expression.right, ReferenceExpression)
            else expression.right
        )
        return expression.model_copy(update={"left": left, "right": right})
    if isinstance(expression, BooleanExpression):
        return expression.model_copy(
            update={
                "operands": tuple(
                    map_references(item, mapper) for item in expression.operands
                )
            }
        )
    if isinstance(expression, NotExpression):
        return expression.model_copy(
            update={"operand": map_references(expression.operand, mapper)}
        )
    if isinstance(expression, ExistsExpression):
        return expression.model_copy(update={"operand": mapper(expression.operand)})
    raise TypeError(f"unsupported expression node: {type(expression).__name__}")


__all__ = [
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
