"""Public declarative Alertissimo DSL surface, validation, and IR lowering."""

from .capability_validation import (
    SurfaceCapabilityCheck,
    SurfaceCapabilityEvidence,
    SurfaceCapabilityReport,
    SurfaceCapabilityStatus,
    SurfaceCapabilityValidationError,
    validate_surface_capabilities,
)
from .lowering import (
    SurfaceLoweringError,
    compile_surface_to_ir,
    lower_surface_to_ir,
)
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
    "SurfaceCapabilityCheck",
    "SurfaceCapabilityEvidence",
    "SurfaceCapabilityReport",
    "SurfaceCapabilityStatus",
    "SurfaceCapabilityValidationError",
    "SurfaceClause",
    "SurfaceLoweringError",
    "SurfaceScript",
    "SurfaceValidationIssue",
    "SurfaceValidationReport",
    "ValidationSeverity",
    "WhereClause",
    "WithinClause",
    "compile_surface_to_ir",
    "grammar_text",
    "lower_surface_to_ir",
    "parse_surface_script",
    "resolve_record_type",
    "validate_surface_capabilities",
    "validate_surface_semantics",
)
