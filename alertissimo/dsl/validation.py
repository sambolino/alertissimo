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


class _SemanticPaths(Protocol):
    record_types: frozenset[str]

    def is_valid(self, semantic_path: str) -> bool: ...


_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
_DOTTED_PATH = re.compile(
    r"\b[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_{}-]+)+\b"
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

    matches: list[str] = []
    for token in _WORD.findall(product):
        noun = _normalize_noun(token)
        if noun in record_types and noun not in matches:
            matches.append(noun)
    return matches[0] if len(matches) == 1 else None


def _unqualified_path_valid(
    path: str,
    semantic_paths: _SemanticPaths,
) -> bool | None:
    head, dot, tail = path.partition(".")
    if not dot or head not in semantic_paths.record_types:
        return None
    return semantic_paths.is_valid(f"{head}@dsl.{tail}")


def validate_surface_semantics(
    surface: SurfaceScript,
    *,
    semantic_paths: _SemanticPaths | None = None,
) -> SurfaceValidationReport:
    """Validate ontology-grounded intent without asking provider capabilities.

    This stage deliberately does not reject unknown origins, brokers, algorithms,
    external counterpart streams, or ranking methods. Those belong to capability
    validation and lowering. It validates what is already knowable from the
    ontology: requested record nouns and explicit ontology paths.
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

        if isinstance(clause, OrderByClause):
            valid = _unqualified_path_valid(clause.expression, model)
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
            for path in _DOTTED_PATH.findall(clause.condition):
                valid = _unqualified_path_valid(path, model)
                if valid is False:
                    issues.append(
                        SurfaceValidationIssue(
                            severity=ValidationSeverity.ERROR,
                            code="invalid_condition_path",
                            message=(
                                "condition path is not valid in the ontology: "
                                f"{path!r}"
                            ),
                            clause_index=index,
                        )
                    )

    return SurfaceValidationReport(issues=tuple(issues))


__all__ = [
    "SurfaceValidationIssue",
    "SurfaceValidationReport",
    "ValidationSeverity",
    "resolve_record_type",
    "validate_surface_semantics",
]
