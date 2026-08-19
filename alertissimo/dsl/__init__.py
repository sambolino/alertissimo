"""Public declarative DSL surface.

The DSL package intentionally exposes user intent only.  Ontology validation,
capability resolution, and lowering to orchestration IR live in later layers.
"""

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
    parse_surface_script,
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
    "WhereClause",
    "WithinClause",
    "parse_surface_script",
)
