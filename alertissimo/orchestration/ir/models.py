"""Declarative, provider-independent orchestration intermediate representation.

The inheritance tree is intentionally part of the IR vocabulary: it records whether
an operation discovers, retrieves, derives, analyzes, or acts.  These distinctions
remain semantic even if a future planner can execute several operations with one
provider request.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


NonEmptyStr = Annotated[str, Field(min_length=1, pattern=r".*\S.*")]
PositiveFloat = Annotated[float, Field(gt=0)]


class IRModel(BaseModel):
    """Common configuration for immutable-in-shape IR value objects."""

    model_config = ConfigDict(extra="forbid")


class Source(IRModel):
    """Optional constraints on the execution source selected by a planner."""

    broker: NonEmptyStr | None = None
    origin: NonEmptyStr | None = None

    @model_validator(mode="after")
    def require_constraint(self) -> Source:
        if self.broker is None and self.origin is None:
            raise ValueError("source requires at least one of broker or origin")
        return self


class TimeContext(IRModel):
    """Declarative temporal constraints, without provider query translation."""

    window: timedelta | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    relative_to: NonEmptyStr | None = None
    offset: timedelta | None = None
    sampling: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_range(self) -> TimeContext:
        if self.start_time is not None and self.end_time is not None:
            try:
                invalid = self.start_time > self.end_time
            except TypeError as exc:
                raise ValueError("start_time and end_time must use compatible timezones") from exc
            if invalid:
                raise ValueError("start_time must be before or equal to end_time")
        return self


class Step(IRModel):
    """Common source constraints shared by canonical Alertissimo operations."""

    sources: list[Source] = Field(default_factory=list)


TargetKind = Literal["object", "alert", "source", "detection"]


class TargetSelector(IRModel):
    """Explicit selection of one or more entities in an optional namespace."""

    ids: list[NonEmptyStr] = Field(min_length=1)
    kind: TargetKind | None = None

    @field_validator("ids")
    @classmethod
    def reject_duplicate_ids(cls, ids: list[str]) -> list[str]:
        if len(set(ids)) != len(ids):
            raise ValueError("ids must not contain duplicates")
        return ids


class LookupStep(Step):
    """Resolve an already-known identifier rather than discover by constraints.

    Object, alert, source, and detection identifiers may resolve to different
    semantic entity families.  Consequently lookup remains outside SearchStep and
    does not require ``semantic_type`` until identifier namespaces are formalized.
    """

    op: Literal["lookup"] = "lookup"
    id: NonEmptyStr


class SearchStep(Step):
    """Conceptual base for provider/capability discovery of SemanticRecords.

    Search asks the available provider space to discover records matching a query.
    Every search therefore declares the expected SemanticRecord family.  It does
    not mean reducing records that are already in the working context; that is
    FilterStep's deliberately separate meaning.
    """

    semantic_type: NonEmptyStr


class SemanticSearchStep(SearchStep):
    """Discover SemanticRecords through semantic predicates or criteria."""

    op: Literal["semantic_search"] = "semantic_search"
    criteria: dict[str, Any] = Field(default_factory=dict)
    time_context: TimeContext | None = None


class ConeSearchStep(SearchStep):
    """Discover records in a cone (RA/Dec degrees, radius arcseconds)."""

    op: Literal["cone_search"] = "cone_search"
    ra: Annotated[float, Field(ge=0, lt=360)]
    dec: Annotated[float, Field(ge=-90, le=90)]
    radius: PositiveFloat
    magnitude_limit: float | None = None
    time_context: TimeContext | None = None


class SqlQueryStep(SearchStep):
    """Discover a declared record family using a provider's SQL-like capability."""

    op: Literal["sql_query"] = "sql_query"
    query: NonEmptyStr


class FilterStep(Step):
    """Reduce data already present in the current working context.

    Unlike SearchStep, FilterStep does not ask providers to discover records.  For
    example, semantic-searching summaries for supernovae may become a provider
    query, whereas filtering current candidates by decline rate operates on
    material already available to the workflow/session/Portfolio context.  A
    future planner may push this predicate into an upstream query as an execution
    optimization, but doing so must not change the IR meaning.  No input/result-set
    model is implied here yet.
    """

    op: Literal["filter"] = "filter"
    criteria: dict[str, Any]


class GetStep(Step):
    """Conceptual base for retrieving already-existing information or evidence.

    Get operations obtain a semantic record, product, or assertion from an
    available source.  They do not compute a new Alertissimo result locally and do
    not request that a facility generate a new observation or product.
    """

    target: TargetSelector | None = None


class GetLightcurveStep(GetStep):
    """Retrieve an existing lightcurve; LightcurveStep constructs a local one."""

    op: Literal["get_lightcurve"] = "get_lightcurve"
    bands: list[NonEmptyStr] | None = None
    time_context: TimeContext | None = None


class GetCrossmatchStep(GetStep):
    """Retrieve an existing crossmatch result rather than perform association."""

    op: Literal["get_crossmatch"] = "get_crossmatch"
    catalog: NonEmptyStr | None = None
    radius: PositiveFloat | None = None


class GetCutoutStep(GetStep):
    op: Literal["get_cutout"] = "get_cutout"
    format: NonEmptyStr | None = None
    size: PositiveFloat | None = None


class GetForcedPhotometryStep(GetStep):
    """Retrieve existing forced photometry, never request its generation.

    Generation belongs to FollowupRequestStep because it causes a new product.
    """

    op: Literal["get_forced_photometry"] = "get_forced_photometry"
    bands: list[NonEmptyStr] | None = None
    time_context: TimeContext | None = None


class GetClassificationStep(GetStep):
    """Retrieve an existing assertion; ClassifyStep runs a model to create one."""

    op: Literal["get_classification"] = "get_classification"


class GetSpectrumStep(GetStep):
    op: Literal["get_spectrum"] = "get_spectrum"
    time_context: TimeContext | None = None


class GetDataProductStep(GetStep):
    op: Literal["get_data_product"] = "get_data_product"
    product_type: NonEmptyStr | None = None


class LightcurveStep(Step):
    """Produce an Alertissimo-derived lightcurve from available evidence.

    This is distinct from retrieving an existing provider lightcurve.  TODO: the
    exact construction semantics (such as unifying detections, forced photometry,
    surveys, and sources) are intentionally provisional and will be iterated.
    """

    op: Literal["lightcurve"] = "lightcurve"
    target: TargetSelector | None = None
    bands: list[NonEmptyStr] | None = None
    time_context: TimeContext | None = None


class MatchStep(Step):
    """Locally perform a scientific association/matching operation.

    Match asks whether astronomical entities or records are spatially, temporally,
    probabilistically, or otherwise associated.  It differs from GetCrossmatchStep,
    which retrieves somebody else's result, and from CompareStep, which asks how
    already-selected values or assertions agree or differ.  Geometry and input-set
    models remain intentionally provisional pending the use-case census.
    """

    op: Literal["match"] = "match"
    target: TargetSelector | None = None
    method: NonEmptyStr | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class AnalyzeStep(Step):
    """Conceptual base for locally deriving analytical information from available data."""

    target: TargetSelector | None = None


class MethodAnalysisStep(AnalyzeStep):
    """Run a named open-vocabulary algorithm without an algorithm-specific Step class."""

    op: Literal["analyze"] = "analyze"
    method: NonEmptyStr
    params: dict[str, Any] = Field(default_factory=dict)
    time_context: TimeContext | None = None


class ClassifyStep(AnalyzeStep):
    """Run a classifier to produce a new classification, rather than retrieve one."""

    op: Literal["classify"] = "classify"
    method: NonEmptyStr | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class AggregateStep(AnalyzeStep):
    """Compute aggregate or statistical information from available data."""

    op: Literal["aggregate"] = "aggregate"
    method: NonEmptyStr | None = None
    field: NonEmptyStr | None = None
    group_by: list[NonEmptyStr] | None = None


class CompareStep(AnalyzeStep):
    """Compare selected values, assertions, or representations for entities.

    Comparison measures difference or agreement; unlike MatchStep, it does not ask
    whether astronomical entities are scientifically associated. ``target`` selects
    entities, while ``comparison_target`` names the semantic comparison operand.
    """

    op: Literal["compare"] = "compare"
    comparison_target: NonEmptyStr | None = None
    method: NonEmptyStr | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class UtilityScoreStep(AnalyzeStep):
    """Compute objective-relative candidate or program utility/prioritization.

    Examples include follow-up priority, scientific utility, observability-weighted
    target value, and telescope-time utility.  This term explicitly does not mean a
    classifier or anomaly score, quality, significance, or an arbitrary numeric
    scientific measurement.  Its ontology/session placement remains unresolved.
    """

    op: Literal["utility_score"] = "utility_score"
    method: NonEmptyStr | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class ConfirmStep(Step):
    """Require corroboration while its future relationship to Compare/Match remains open."""

    op: Literal["confirm"] = "confirm"
    target: TargetSelector | None = None
    required_agreement: Annotated[int, Field(ge=1)] = 1

    @model_validator(mode="after")
    def validate_explicit_source_count(self) -> ConfirmStep:
        if self.sources and self.required_agreement > len(self.sources):
            raise ValueError("required_agreement cannot exceed the explicit source count")
        return self


class MonitorStep(Step):
    """Monitor a semantic stream; transport mechanisms such as Kafka are not IR operations."""

    op: Literal["monitor"] = "monitor"
    stream: NonEmptyStr | None = None
    criteria: dict[str, Any] = Field(default_factory=dict)
    time_context: TimeContext | None = None


class ActionStep(Step):
    """Conceptual base for outward effects rather than retrieval or local analysis."""


class FollowupRequestStep(ActionStep):
    """Cause/request a new observation or product, unlike GetStep retrieval."""

    op: Literal["followup_request"] = "followup_request"
    target: TargetSelector | None = None
    request_type: NonEmptyStr
    facility: NonEmptyStr | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class NotifyStep(ActionStep):
    """Send a generic notification; channel-specific aliases belong to a later DSL."""

    op: Literal["notify"] = "notify"
    channel: NonEmptyStr
    recipient: NonEmptyStr | None = None
    message: NonEmptyStr
    params: dict[str, Any] = Field(default_factory=dict)


class ExportStep(ActionStep):
    """Export/save data without encoding destination-specific DSL aliases."""

    op: Literal["export"] = "export"
    destination: NonEmptyStr
    format: NonEmptyStr | None = None


StepUnion = Annotated[
    LookupStep | SemanticSearchStep | ConeSearchStep | SqlQueryStep | FilterStep
    | GetLightcurveStep | GetCrossmatchStep | GetCutoutStep
    | GetForcedPhotometryStep | GetClassificationStep | GetSpectrumStep
    | GetDataProductStep | LightcurveStep | MatchStep | MethodAnalysisStep
    | ClassifyStep | AggregateStep | CompareStep | UtilityScoreStep | ConfirmStep
    | MonitorStep | FollowupRequestStep | NotifyStep | ExportStep,
    Field(discriminator="op"),
]


class WorkflowIR(IRModel):
    """An ordered collection of canonical operations, with no execution state."""

    steps: list[StepUnion]
    name: NonEmptyStr | None = None
    description: NonEmptyStr | None = None


__all__ = [
    "ActionStep", "AggregateStep", "AnalyzeStep", "ClassifyStep", "CompareStep",
    "ConeSearchStep", "ConfirmStep", "ExportStep", "FilterStep",
    "FollowupRequestStep", "GetClassificationStep", "GetCrossmatchStep",
    "GetCutoutStep", "GetDataProductStep", "GetForcedPhotometryStep",
    "GetLightcurveStep", "GetSpectrumStep", "GetStep", "LightcurveStep",
    "LookupStep", "MatchStep", "MethodAnalysisStep", "MonitorStep", "NotifyStep",
    "SearchStep", "SemanticSearchStep", "Source", "SqlQueryStep", "Step",
    "StepUnion", "TargetKind", "TargetSelector", "TimeContext", "UtilityScoreStep",
    "WorkflowIR",
]
