"""Static ontology validation for the declarative DSL surface."""

from __future__ import annotations

from enum import Enum
import re
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from .surface import FilterClause, OrderByClause, RequirementClause, SurfaceScript, WhereClause


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
    """One semantic record family explicitly referenced by an expression path."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    noun: str
    producer: str | None = None
    channel: str | None = None


class _SemanticPaths(Protocol):
    record_types: frozenset[str]

    def is_valid(self, semantic_path: str) -> bool: ...


_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
_PATH = re.compile(
    r"\b(?P<root>[A-Za-z][A-Za-z0-9_-]*(?:@[A-Za-z][A-Za-z0-9_-]*(?::[A-Za-z][A-Za-z0-9_-]*)?)?)"
    r"\.(?P<tail>[A-Za-z0-9_{}-]+(?:\.[A-Za-z0-9_{}-]+)*)\b"
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


def extract_semantic_record_references(
    expression: str,
    record_types: frozenset[str],
) -> tuple[SemanticRecordReference, ...]:
    """Extract explicit record-family dependencies from dotted expression paths."""

    refs: list[SemanticRecordReference] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for match in _PATH.finditer(expression):
        noun, producer, channel = _reference_parts(match.group("root"))
        noun = _normalize_noun(noun)
        if noun not in record_types:
            continue
        key = (noun, producer, channel)
        if key in seen:
            continue
        seen.add(key)
        refs.append(
            SemanticRecordReference(
                noun=noun,
                producer=producer.lower() if producer else None,
                channel=channel.lower() if channel else None,
            )
        )
    return tuple(refs)


def _path_valid(
    path: str,
    semantic_paths: _SemanticPaths,
    *,
    scoped_noun: str | None = None,
) -> bool | None:
    match = _PATH.fullmatch(path)
    if match is None:
        return None
    root = match.group("root")
    tail = match.group("tail")
    noun, _, _ = _reference_parts(root)
    noun = _normalize_noun(noun)
    if noun in semantic_paths.record_types:
        return semantic_paths.is_valid(f"{noun}@dsl.{tail}")
    if scoped_noun is not None:
        return semantic_paths.is_valid(f"{scoped_noun}@dsl.{path}")
    return None


def _validate_expression_paths(
    expression: str,
    model: _SemanticPaths,
    *,
    clause_index: int,
    code: str,
    scoped_noun: str | None = None,
) -> list[SurfaceValidationIssue]:
    issues: list[SurfaceValidationIssue] = []
    for match in _PATH.finditer(expression):
        path = match.group(0)
        valid = _path_valid(path, model, scoped_noun=scoped_noun)
        if valid is False:
            issues.append(
                SurfaceValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code=code,
                    message=f"condition path is not valid in the ontology: {path!r}",
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
    validation and lowering. It validates requested record nouns and explicit or
    WITH-scoped ontology paths.
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
                        )
                    )

        if isinstance(clause, OrderByClause):
            valid = _path_valid(clause.expression, model)
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


__all__ = [
    "SemanticRecordReference",
    "SurfaceValidationIssue",
    "SurfaceValidationReport",
    "ValidationSeverity",
    "extract_semantic_record_references",
    "resolve_record_type",
    "validate_surface_semantics",
]
