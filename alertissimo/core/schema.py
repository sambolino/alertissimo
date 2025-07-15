from pydantic import BaseModel, Field
from typing import List, Optional, Union


class Source(BaseModel):
    broker: str                         # e.g. "alerce", "fink"
    stream: Optional[str] = None        # e.g. "ztf", "alerts"
    config: Optional[dict] = {}         # Additional broker-specific config


class FilterCondition(BaseModel):
    attribute: str                      # e.g. "rmag", "ztf.score"
    op: str                             # e.g. "<", "==", "in"
    value: Union[str, float, int]
    source: Optional[Source] = None     # Optional broker context


class Classifier(BaseModel):
    method: str                         # e.g. "xgb", "parsnip", "custom"
    model: str                          # Path or model name
    source: Optional[Source] = None


class ScoringRule(BaseModel):
    name: str                           # e.g. "priority"
    formula: str                        # Custom formula using pipeline variables


class ActStep(BaseModel):
    export: Optional[str] = None        # e.g. "csv", "yaml", "lasair"
    path: Optional[str] = None          # Local path or remote endpoint
    notify: Optional[str] = None        # e.g. "slack", "email"
    source: Optional[Source] = None     # Optional for broker-linked actions


class EnrichmentStep(BaseModel):
    type: str                           # e.g. "historical_lc", "crossmatch"
    source: Optional[Source] = None     # Broker providing enrichment
    params: Optional[dict] = {}         # e.g. {"radius": 5, "bands": ["g", "r"]}


class ConfirmationRule(BaseModel):
    object_id: str                      # Alert or target object ID
    required_agreement: int = 2         # Minimum brokers that must agree
    sources: List[Source]               # Brokers to query for confirmation


class WorkflowIR(BaseModel):
    name: str
    schedule: Optional[str] = None      # For cron/timed executions
    confirm: Optional[ConfirmationRule] = None
    filter: Optional[List[FilterCondition]] = []
    enrich: Optional[List[EnrichmentStep]] = []
    classify: Optional[List[Classifier]] = []
    score: Optional[List[ScoringRule]] = []
    act: Optional[List[ActStep]] = []

