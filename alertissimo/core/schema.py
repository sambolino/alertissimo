from enum import Enum
from typing import List, Optional, Union, Literal
from pydantic import BaseModel, Field, model_validator


# ---- Capability Definitions ----

class Capability(str, Enum):
    conesearch = "conesearch"
    object_query = "object_query"
    lightcurve = "lightcurve"
    crossmatch = "crossmatch"
    cutout = "cutout"
    classify = "classify"
    sql_query = "sql_query"
    objects_query = "objects_query"
    kafka_stream = "kafka_stream"


# ---- Capability Requirement Logic ----

class CapabilityRequirement(BaseModel):
    capability: Optional[Capability] = None
    any_of: Optional[List[Capability]] = None
    all_of: Optional[List[Capability]] = None
    
    @model_validator(mode="after")
    def validate_structure(self) -> "CapabilityRequirement":
        count = sum(
            1 for v in [self.capability, self.any_of, self.all_of] if v
        )
        if count != 1:
            raise ValueError(
                "Exactly one of 'capability', 'any_of' or 'all_of' must be specified."
            )
        return self

    def matches(self, available_caps: List[str]) -> bool:
        caps = set(available_caps)
        if self.capability:
            return self.capability in caps
        if self.any_of:
            return any(cap in caps for cap in self.any_of)
        if self.all_of:
            return all(cap in caps for cap in self.all_of)
        return False


# ---- Core Schemas ----

class Source(BaseModel):
    broker: str
    stream: Optional[str] = None
    config: Optional[dict] = Field(default_factory=dict)


class FilterCondition(BaseModel):
    required: CapabilityRequirement = Field(
        default=CapabilityRequirement(any_of=[
            Capability.objects_query,
            Capability.sql_query,
            Capability.conesearch
        ]),
        description="Requires any kind of parametrized search"
    )
    attribute: str
    op: str
    value: Union[str, float, int]
    source: Optional[Source] = None


class Classifier(BaseModel):
    required: CapabilityRequirement = Field(
        default=CapabilityRequirement(capability=Capability.classify),
        description="Requires classification capability"
    )
    method: str
    model: str
    source: Optional[Source] = None


class ScoringRule(BaseModel):
    name: str
    formula: str


class ActStep(BaseModel):
    required: Optional[CapabilityRequirement] = None
    export: Optional[str] = None
    path: Optional[str] = None
    notify: Optional[str] = None
    source: Optional[Source] = None


class EnrichmentStep(BaseModel):
    #type: str
    source: Source
    params: Optional[dict] = Field(default_factory=dict)
    #required: CapabilityRequirement | None = None


class LightcurveStep(EnrichmentStep):
    #type: Literal["lightcurve"] #here we can control later detections, nondetections etc
    # commented out because it would require explicitly stating lightcurve type=lightcurve in dsl
    required: CapabilityRequirement = Field(
        default=CapabilityRequirement(capability=Capability.lightcurve)
    )


class CrossmatchStep(EnrichmentStep):
    #type: Literal["crossmatch"]
    required: CapabilityRequirement = Field(
        default=CapabilityRequirement(capability=Capability.crossmatch)
    )
    catalogs: Optional[List[str]] = Field(default_factory=list)


class CutoutStep(EnrichmentStep):
    #type: Literal["cutout"]
    required: CapabilityRequirement = Field(
        default=CapabilityRequirement(capability=Capability.cutout)
    )

class KafkaStep(EnrichmentStep):
    type: Literal["realtime_monitoring"]
    required: CapabilityRequirement = Field(
        default=CapabilityRequirement(capability=Capability.kafka_stream)
    )

class FindObject(BaseModel):
    required: CapabilityRequirement = Field(
        default=CapabilityRequirement(capability=Capability.object_query),
        description="Requires object query capability"
    )
    object_id: str
    sources: List[Source]

class ConfirmationRule(FindObject):
    required_agreement: int = 2


class WorkflowIR(BaseModel):
    name: str
    schedule: Optional[str] = None
    confirm: Optional[ConfirmationRule] = None
    findobject: Optional[FindObject] = None
    filter: Optional[List[FilterCondition]] = Field(default_factory=list)
    enrich: Optional[List[EnrichmentStep]] = Field(default_factory=list)
    classify: Optional[List[Classifier]] = Field(default_factory=list)
    score: Optional[List[ScoringRule]] = Field(default_factory=list)
    act: Optional[List[ActStep]] = Field(default_factory=list)
