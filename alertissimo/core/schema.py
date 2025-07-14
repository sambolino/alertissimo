
from pydantic import BaseModel, Field
from typing import List, Optional, Union

class FilterCondition(BaseModel):
    attribute: str
    op: str
    value: Union[str, float, int]

class Classifier(BaseModel):
    method: str
    model: str

class ScoringRule(BaseModel):
    name: str
    formula: str

class ActStep(BaseModel):
    export: Optional[str] = None
    path: Optional[str] = None
    notify: Optional[str] = None

class Source(BaseModel):
    broker: str
    stream: str
    config: Optional[dict] = {}

class WorkflowIR(BaseModel):
    name: str
    schedule: Optional[str]
    source: Source
    filter: Optional[List[FilterCondition]] = []
    enrich: Optional[List[str]] = []
    classify: Optional[List[Classifier]] = []
    score: Optional[List[ScoringRule]] = []
    act: Optional[List[ActStep]] = []
