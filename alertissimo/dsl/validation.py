"""Static ontology validation for the declarative DSL surface."""

from __future__ import annotations

from enum import Enum
import re
from typing import Protocol

from alertissimo.orchestration.ir import WorkflowIR

from pydantic import BaseModel, ConfigDict

from .expression import (
    Expression,
    ExpressionModel,
    ExpressionParseError,
    ReferenceExpression,
    iter_references,
    parse_expression,
)
from .fragment import fragment_surface_context
from .surface import (
    FilterClause,
    OrderByClause,
    RequirementClause,
    SurfaceScript,
    SurfaceFragment,
    WhereClause,
)


class ValidationSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class SurfaceValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    severity: ValidationSeverity
    code: str
    message: str
    clause_index: int | None = None


class SurfaceValidationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    issues: tuple[SurfaceValidationIssue, ...] = ()

    @property
    def errors(self) -> tuple[SurfaceValidationIssue, ...]:
        return tuple(
            issue
            for issue in self.issues
            if issue.severity is ValidationSeverity.ERROR
        )

    @property
    def warnings(self) -> tuple[SurfaceValidationIssue, ...]:
        return tuple(
            issue
            for issue in self.issues
            if issue.severity is ValidationSeverity.WARNING
        )

    @property
    def is_valid(self) -> bool:
        return not self.errors


class SemanticRecordReference(BaseModel):
    """One semantic record family explicitly referenced by an expression."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    noun: str
    producer: str | None = None
    channel: str | None = None


class _SemanticPaths(Protocol):
    record_types: frozenset[str]

    def is_valid(self, semantic_path: str) -> bool: ...


_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
_ORDER_PATH = re.compile(
    r"^(?P<root>[A-Za-z][A-Za-z0-9_-]*(?:@[A-Za-z][A-Za-z0-9_-]*"
    r"(?::[A-Za-z][A-Za-z0-9_-]*)?)?)"
    r"\.(?P<tail>[A-Za-z0-9_{}-]+(?:\.[A-Za-z0-9_{}-]+)*)$"
)


def _semantic_path_model() -> _SemanticPaths:
    from alertissimo.data_layer.semantic_model import SemanticPathModel

    return SemanticPathModel.from_ontology()


def _normalize_noun(token: str) -> str:
    return token.lower().replace("-", "_")


def resolve_record_type(
    product: str,
    record_types: frozenset[str],
) -> str | None:
    """Resolve one ontology record noun embedded in a user requirement phrase."""

    words = [_normalize_noun(token) for token in _WORD.findall(product)]
    matches: list[str] = []
    for start in range(len(words)):
        for stop in range(start + 1, min(len(words), start + 3) + 1):
            noun = "_".join(words[start:stop])
            if noun in record_types and noun not in matches:
                matches.append(noun)
    return matches[0] if len(matches) == 1 else None


def _reference_parts(root: str) -> tuple[str, str | None, str | None]:
    noun, at, qualifiers = root.partition("@")
    if not at:
        return noun, None, None
    producer, colon, channel = qualifiers.partition(":")
    return noun, producer or None, (channel or None) if colon else None


def resolve_expression_references(
    expression: Expression | str,
    record_types: frozenset[str],
    *,
    scoped_noun: str | None = None,
    scoped_producer: str | None = None,
    scoped_channel: str | None = None,
) -> Expression:
    """Resolve syntactic references against ontology record scope.

    Fully qualified or record-rooted field references resolve absolutely.
    Unqualified references inside a WITH predicate resolve relative to that
    requirement's semantic record family and inherit its producer/channel
    qualifiers. A bare record noun in a comparison is deliberately *not*
    interpreted as a scalar or ``best`` value; bare record nouns resolve only
    under ``exists`` until an explicit semantic alias is defined.
    """

    parsed = parse_expression(expression) if isinstance(expression, str) else expression

    def resolve_reference(
        reference: ReferenceExpression,
        *,
        allow_bare_record: bool,
    ) -> ReferenceExpression:
        root = _normalize_noun(reference.root)
        absolute_evidence = bool(
            reference.path
            or reference.producer is not None
            or reference.channel is not None
            or allow_bare_record
        )
        if root in record_types and absolute_evidence:
            producer = reference.producer
            channel = reference.channel
            if scoped_noun == root:
                producer = producer or scoped_producer
                channel = channel or scoped_channel
            return reference.model_copy(
                update={
                    "root": root,
                    "record_type": root,
                    "producer": producer,
                    "channel": channel,
                    "resolution": "absolute",
                }
            )

        if reference.producer is not None or reference.channel is not None:
            return reference.model_copy(update={"root": root})

        if scoped_noun is not None:
            return reference.model_copy(
                update={
                    "root": root,
                    "record_type": scoped_noun,
                    "producer": scoped_producer,
                    "channel": scoped_channel,
                    "path": (root, *reference.path),
                    "resolution": "scoped",
                }
            )

        return reference.model_copy(update={"root": root})

    def resolve_node(node: ExpressionModel) -> ExpressionModel:
        from .expression import (
            BooleanExpression,
            ComparisonExpression,
            ExistsExpression,
            NotExpression,
        )

        if isinstance(node, ComparisonExpression):
            left = (
                resolve_reference(node.left, allow_bare_record=False)
                if isinstance(node.left, ReferenceExpression)
                else node.left
            )
            right = (
                resolve_reference(node.right, allow_bare_record=False)
                if isinstance(node.right, ReferenceExpression)
                else node.right
            )
            return node.model_copy(update={"left": left, "right": right})
        if isinstance(node, BooleanExpression):
            return node.model_copy(
                update={
                    "operands": tuple(resolve_node(item) for item in node.operands)
                }
            )
        if isinstance(node, NotExpression):
            return node.model_copy(update={"operand": resolve_node(node.operand)})
        if isinstance(node, ExistsExpression):
            return node.model_copy(
                update={
                    "operand": resolve_reference(
                        node.operand,
                        allow_bare_record=True,
                    )
                }
            )
        raise TypeError(f"unsupported expression node: {type(node).__name__}")

    resolved = resolve_node(parsed)
    return resolved  # type: ignore[return-value]


def extract_semantic_record_references(
    expression: Expression | str,
    record_types: frozenset[str],
    *,
    scoped_noun: str | None = None,
    scoped_producer: str | None = None,
    scoped_channel: str | None = None,
) -> tuple[SemanticRecordReference, ...]:
    """Extract resolved record-family dependencies from one formal expression."""

    resolved = resolve_expression_references(
        expression,
        record_types,
        scoped_noun=scoped_noun,
        scoped_producer=scoped_producer,
        scoped_channel=scoped_channel,
    )
    refs: list[SemanticRecordReference] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for reference in iter_references(resolved):
        if reference.record_type is None:
            continue
        key = (
            reference.record_type,
            reference.producer,
            reference.channel,
        )
        if key in seen:
            continue
        seen.add(key)
        refs.append(
            SemanticRecordReference(
                noun=reference.record_type,
                producer=reference.producer,
                channel=reference.channel,
            )
        )
    return tuple(refs)


def _order_path_valid(
    path: str,
    semantic_paths: _SemanticPaths,
) -> bool | None:
    match = _ORDER_PATH.fullmatch(path)
    if match is None:
        return None
    root = match.group("root")
    tail = match.group("tail")
    noun, _, _ = _reference_parts(root)
    noun = _normalize_noun(noun)
    if noun in semantic_paths.record_types:
        return semantic_paths.is_valid(f"{noun}@dsl.{tail}")
    return None


def _reference_display(reference: ReferenceExpression) -> str:
    if reference.resolution == "scoped":
        return reference.field_path
    root = reference.record_type or reference.root
    if reference.producer is not None:
        root += f"@{reference.producer}"
        if reference.channel is not None:
            root += f":{reference.channel}"
    return root + (f".{reference.field_path}" if reference.field_path else "")


def _validate_expression_paths(
    expression: str,
    model: _SemanticPaths,
    *,
    clause_index: int,
    code: str,
    scoped_noun: str | None = None,
    scoped_producer: str | None = None,
    scoped_channel: str | None = None,
) -> list[SurfaceValidationIssue]:
    try:
        resolved = resolve_expression_references(
            expression,
            model.record_types,
            scoped_noun=scoped_noun,
            scoped_producer=scoped_producer,
            scoped_channel=scoped_channel,
        )
    except ExpressionParseError as exc:
        return [
            SurfaceValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="invalid_expression_syntax",
                message=str(exc),
                clause_index=clause_index,
            )
        ]

    issues: list[SurfaceValidationIssue] = []
    for reference in iter_references(resolved):
        if (
            reference.record_type is None
            and (reference.producer is not None or reference.channel is not None)
        ):
            issues.append(
                SurfaceValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code=code,
                    message=(
                        "expression references an unknown ontology record type: "
                        f"{_reference_display(reference)!r}"
                    ),
                    clause_index=clause_index,
                )
            )
            continue
        if reference.record_type is None or not reference.path:
            continue
        semantic_path = (
            f"{reference.record_type}@dsl.{'.'.join(reference.path)}"
        )
        if not model.is_valid(semantic_path):
            issues.append(
                SurfaceValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code=code,
                    message=(
                        "condition path is not valid in the ontology: "
                        f"{_reference_display(reference)!r}"
                    ),
                    clause_index=clause_index,
                )
            )
    return issues


def validate_surface_semantics(
    surface: SurfaceScript,
    *,
    semantic_paths: _SemanticPaths | None = None,
) -> SurfaceValidationReport:
    """Validate ontology-grounded intent without asking provider capabilities.

    This stage deliberately does not reject unknown origins, brokers, algorithms,
    external counterpart streams, or ranking methods. Those belong to capability
    validation and lowering. Predicate syntax is formalized independently in
    ``expression.lark`` and semantic references are resolved structurally rather
    than extracted with regular expressions.
    """

    model = semantic_paths or _semantic_path_model()
    issues: list[SurfaceValidationIssue] = []

    for index, clause in enumerate(surface.clauses):
        if isinstance(clause, RequirementClause):
            noun = resolve_record_type(clause.product, model.record_types)
            if noun is None:
                issues.append(
                    SurfaceValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        code="unknown_requirement_product",
                        message=(
                            "requirement does not resolve to exactly one ontology "
                            f"record type: {clause.product!r}"
                        ),
                        clause_index=index,
                    )
                )
            else:
                for predicate in clause.predicates:
                    issues.extend(
                        _validate_expression_paths(
                            predicate,
                            model,
                            clause_index=index,
                            code="invalid_requirement_predicate_path",
                            scoped_noun=noun,
                            scoped_producer=clause.source,
                            scoped_channel=(
                                clause.via or surface.candidates.broker
                            ),
                        )
                    )

        if isinstance(clause, OrderByClause):
            valid = _order_path_valid(clause.expression, model)
            if valid is False:
                issues.append(
                    SurfaceValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        code="invalid_order_path",
                        message=(
                            "order by path is not valid in the ontology: "
                            f"{clause.expression!r}"
                        ),
                        clause_index=index,
                    )
                )

        if isinstance(clause, (WhereClause, FilterClause)):
            issues.extend(
                _validate_expression_paths(
                    clause.condition,
                    model,
                    clause_index=index,
                    code="invalid_condition_path",
                )
            )

    return SurfaceValidationReport(issues=tuple(issues))


def validate_surface_fragment_semantics(
    fragment: SurfaceFragment,
    base_workflow: WorkflowIR,
    *,
    semantic_paths: _SemanticPaths | None = None,
) -> SurfaceValidationReport:
    """Validate fragment ontology references using context derived only from IR."""

    return validate_surface_semantics(
        fragment_surface_context(fragment, base_workflow),
        semantic_paths=semantic_paths,
    )


__all__ = [
    "SemanticRecordReference",
    "SurfaceValidationIssue",
    "SurfaceValidationReport",
    "ValidationSeverity",
    "extract_semantic_record_references",
    "resolve_expression_references",
    "resolve_record_type",
    "validate_surface_semantics",
    "validate_surface_fragment_semantics",
]
