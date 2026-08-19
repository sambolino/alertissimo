"""Public declarative Alertissimo DSL surface and static validation."""

from .parser import grammar_text, parse_surface_script
from .surface import (
    AngularRadius,
    CandidateSet,
    DSLParseError,
    Duration,
    FilterClause,
    InsideClause,
    LatestClause,
    MatchClause,
    OrderByClause,
    RankedByClause,
    RequirementClause,
    SurfaceClause,
    SurfaceScript,
    WhereClause,
    WithinClause,
)
from .validation import (
    SurfaceValidationIssue,
    SurfaceValidationReport,
    ValidationSeverity,
    resolve_record_type,
    validate_surface_semantics,
)

__all__ = (
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
    "SurfaceValidationIssue",
    "SurfaceValidationReport",
    "ValidationSeverity",
    "WhereClause",
    "WithinClause",
    "grammar_text",
    "parse_surface_script",
    "resolve_record_type",
    "validate_surface_semantics",
)
