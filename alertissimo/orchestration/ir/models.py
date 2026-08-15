"""Declarative, provider-independent orchestration intermediate representation."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class LookupStep(Step):
    op: Literal["lookup"] = "lookup"
    id: NonEmptyStr


class SearchStep(Step):
    op: Literal["search"] = "search"
    semantic_type: NonEmptyStr
    criteria: dict[str, Any] = Field(default_factory=dict)
    time_context: TimeContext | None = None


class FilterStep(Step):
    op: Literal["filter"] = "filter"
    criteria: dict[str, Any]


class ConeSearchStep(Step):
    """Cone search using right ascension in degrees in the half-open [0, 360) range."""

    op: Literal["cone_search"] = "cone_search"
    ra: Annotated[float, Field(ge=0, lt=360)]
    dec: Annotated[float, Field(ge=-90, le=90)]
    radius: PositiveFloat
    magnitude_limit: float | None = None
    time_context: TimeContext | None = None


class SqlQueryStep(Step):
    op: Literal["sql_query"] = "sql_query"
    query: NonEmptyStr


class TargetStep(Step):
    """Base for operations that may take their target from later context."""

    target_id: NonEmptyStr | None = None


class LightcurveStep(TargetStep):
    op: Literal["lightcurve"] = "lightcurve"
    bands: list[NonEmptyStr] | None = None
    include_detections: bool = True
    include_non_detections: bool = False
    time_context: TimeContext | None = None


class CrossmatchStep(TargetStep):
    op: Literal["crossmatch"] = "crossmatch"
    catalog: NonEmptyStr | None = None
    radius: PositiveFloat | None = None


class CutoutStep(TargetStep):
    op: Literal["cutout"] = "cutout"
    format: NonEmptyStr | None = None
    size: PositiveFloat | None = None


class ForcedPhotometryStep(TargetStep):
    op: Literal["forced_photometry"] = "forced_photometry"
    bands: list[NonEmptyStr] | None = None
    time_context: TimeContext | None = None


class GetClassificationStep(TargetStep):
    op: Literal["get_classification"] = "get_classification"


class GetSpectrumStep(TargetStep):
    op: Literal["get_spectrum"] = "get_spectrum"
    time_context: TimeContext | None = None


class GetDataProductStep(TargetStep):
    op: Literal["get_data_product"] = "get_data_product"
    product_type: NonEmptyStr | None = None


class AnalyzeStep(TargetStep):
    op: Literal["analyze"] = "analyze"
    method: NonEmptyStr
    params: dict[str, Any] = Field(default_factory=dict)
    time_context: TimeContext | None = None


class ClassifyStep(TargetStep):
    op: Literal["classify"] = "classify"
    method: NonEmptyStr | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class AggregateStep(Step):
    op: Literal["aggregate"] = "aggregate"
    method: NonEmptyStr | None = None
    field: NonEmptyStr | None = None
    group_by: list[NonEmptyStr] | None = None


class CompareStep(Step):
    op: Literal["compare"] = "compare"
    target: NonEmptyStr | None = None
    method: NonEmptyStr | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class ConfirmStep(TargetStep):
    op: Literal["confirm"] = "confirm"
    required_agreement: Annotated[int, Field(ge=1)] = 1

    @model_validator(mode="after")
    def validate_explicit_source_count(self) -> ConfirmStep:
        if self.sources and self.required_agreement > len(self.sources):
            raise ValueError("required_agreement cannot exceed the explicit source count")
        return self


class UtilityScoreStep(TargetStep):
    op: Literal["utility_score"] = "utility_score"
    method: NonEmptyStr | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class MonitorStep(Step):
    op: Literal["monitor"] = "monitor"
    stream: NonEmptyStr | None = None
    criteria: dict[str, Any] = Field(default_factory=dict)
    time_context: TimeContext | None = None


class FollowupRequestStep(TargetStep):
    op: Literal["followup_request"] = "followup_request"
    request_type: NonEmptyStr
    facility: NonEmptyStr | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class NotifyStep(Step):
    op: Literal["notify"] = "notify"
    channel: NonEmptyStr
    recipient: NonEmptyStr | None = None
    message: NonEmptyStr
    params: dict[str, Any] = Field(default_factory=dict)


class ExportStep(Step):
    op: Literal["export"] = "export"
    destination: NonEmptyStr
    format: NonEmptyStr | None = None


StepUnion = Annotated[
    LookupStep
    | SearchStep
    | FilterStep
    | ConeSearchStep
    | SqlQueryStep
    | LightcurveStep
    | CrossmatchStep
    | CutoutStep
    | ForcedPhotometryStep
    | GetClassificationStep
    | GetSpectrumStep
    | GetDataProductStep
    | AnalyzeStep
    | ClassifyStep
    | AggregateStep
    | CompareStep
    | ConfirmStep
    | UtilityScoreStep
    | MonitorStep
    | FollowupRequestStep
    | NotifyStep
    | ExportStep,
    Field(discriminator="op"),
]


class WorkflowIR(IRModel):
    """An ordered collection of canonical operations, with no execution state."""

    steps: list[StepUnion]
    name: NonEmptyStr | None = None
    description: NonEmptyStr | None = None


__all__ = [
    "AggregateStep", "AnalyzeStep", "ClassifyStep", "CompareStep", "ConeSearchStep",
    "ConfirmStep", "CrossmatchStep", "CutoutStep", "ExportStep", "FilterStep",
    "FollowupRequestStep", "ForcedPhotometryStep", "GetClassificationStep",
    "GetDataProductStep", "GetSpectrumStep", "LightcurveStep", "LookupStep",
    "MonitorStep", "NotifyStep", "SearchStep", "Source", "SqlQueryStep", "Step",
    "StepUnion", "TimeContext", "UtilityScoreStep", "WorkflowIR",
]
