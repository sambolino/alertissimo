# alertissimo/core/schema.py

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union, Literal
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime, timedelta
from pydantic import BaseModel, Field, model_validator


# ============================================================================
# CAPABILITY DEFINITIONS (1:1 with YAML)
# ============================================================================

class Capability(str, Enum):
    """Raw broker capabilities - exactly what's in YAML"""
    # Search capabilities
    CONESEARCH = "conesearch"
    OBJECT_QUERY = "object_query"
    OBJECTS_QUERY = "objects_query"
    SQL_QUERY = "sql_query"
    
    # Enrichment capabilities
    LIGHTCURVE = "lightcurve"
    CROSSMATCH = "crossmatch"
    CUTOUT = "cutout"
    
    # Analysis capabilities
    CLASSIFY = "classify"
    
    # Streaming capabilities
    KAFKA_STREAM = "kafka_stream"


class CapabilityRequirement(BaseModel):
    """Exactly one capability per concrete model"""
    capability: Capability
    
    def matches(self, available_caps: List[str]) -> bool:
        """Check if this specific capability is available"""
        return self.capability.value in set(available_caps)


# ============================================================================
# IRResult and ExecutionContext
# ============================================================================

@dataclass
class IRResult:
    """Result container - steps know how to update this"""
    object_snapshots: Dict[str, Any] = field(default_factory=dict)
    lightcurves: Dict[str, Any] = field(default_factory=dict)
    crossmatch_results: Dict[str, Any] = field(default_factory=dict)
    kafka_results: Dict[str, bool] = field(default_factory=dict)
    find_results: Dict[str, Any] = field(default_factory=dict)
    filter_results: Dict[str, Any] = field(default_factory=dict)
    classify_results: Dict[str, Any] = field(default_factory=dict)
    score_results: Dict[str, Any] = field(default_factory=dict)
    act_results: Dict[str, Any] = field(default_factory=dict)

    def merge(self, other: 'IRResult'):
        """Merge another IRResult into this one"""
        self.object_snapshots.update(other.object_snapshots)
        self.lightcurves.update(other.lightcurves)
        self.crossmatch_results.update(other.crossmatch_results)
        self.kafka_results.update(other.kafka_results)
        self.find_results.update(other.find_results)

        # For list-type results, we append
        for k, v in other.filter_results.items():
            self.filter_results.setdefault(k, []).extend(v if isinstance(v, list) else [v])
        for k, v in other.classify_results.items():
            self.classify_results.setdefault(k, []).extend(v if isinstance(v, list) else [v])
        for k, v in other.score_results.items():
            self.score_results.setdefault(k, []).extend(v if isinstance(v, list) else [v])
        for k, v in other.act_results.items():
            self.act_results.setdefault(k, []).extend(v if isinstance(v, list) else [v])


class ExecutionContext:
    """Minimal context for sharing between steps"""

    def __init__(self, object_id: str = None):
        self.object_id = object_id
        self.start_time = datetime.now()
        self._broker_cache = {}
        self._data = {}  # For sharing arbitrary data between steps

    def get_broker(self, broker_name: str):
        """Get or create broker instance"""
        if broker_name not in self._broker_cache:
            from alertissimo.core.brokers import get_broker
            self._broker_cache[broker_name] = get_broker(broker_name)
        return self._broker_cache[broker_name]

    def get(self, key: str, default=None):
        """Get shared data"""
        return self._data.get(key, default)

    def set(self, key: str, value: Any):
        """Set shared data"""
        self._data[key] = value

# ============================================================================
# EXECUTABLE MODEL
# ============================================================================

class ExecutableModel(BaseModel, ABC):
    """Base class for all executable steps"""

    @abstractmethod
    def execute(self, context: ExecutionContext, result: IRResult) -> None:
        """
        Execute step and update the result object directly.
        Models know exactly which parts of IRResult to update.
        """
        pass

# ============================================================================
# SOURCE - Meaning source of data, as broker, stream etc
# ============================================================================

class Source(BaseModel):
    broker: str
    stream: Optional[str] = None
    config: Optional[dict] = Field(default_factory=dict)

# ============================================================================
# TIME CONTEXT - Reusable class for temporal parameters
# ============================================================================

from datetime import datetime, timedelta
from typing import Optional, Union, Literal
from pydantic import BaseModel, Field

class TimeContext(BaseModel):
    """
    Temporal context that can be attached to any step.
    Not a verb - just parameters that modify how steps execute.
    """
    # Time window (e.g., last 7 days, next 24 hours)
    window: Optional[timedelta] = None
    
    # Specific time range
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    # Relative time (e.g., "7d before event", "since last run")
    relative_to: Optional[Literal["now", "event", "last_run"]] = None
    offset: Optional[timedelta] = None
    
    # Sampling/interpolation
    sampling: Optional[Literal["raw", "hourly", "daily", "nightly"]] = None
    interpolation: Optional[Literal["linear", "nearest", "cubic"]] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def get_time_range(self, event_time: Optional[datetime] = None) -> tuple[Optional[datetime], Optional[datetime]]:
        """Calculate actual time range based on context"""
        now = datetime.now()
        
        if self.start_time and self.end_time:
            return self.start_time, self.end_time
        
        if self.window:
            if self.relative_to == "event" and event_time:
                end = event_time
                start = event_time - self.window
            elif self.relative_to == "last_run":
                # This would need state management
                pass
            else:  # default: relative to now
                end = now
                start = now - self.window
            return start, end
        
        return None, None
    
    def apply_to_query(self, query_params: dict) -> dict:
        """Add time parameters to broker query"""
        start, end = self.get_time_range()
        if start:
            query_params["start_mjd"] = start.timestamp() / 86400  # Convert to MJD
        if end:
            query_params["end_mjd"] = end.timestamp() / 86400
        if self.sampling:
            query_params["sampling"] = self.sampling
        return query_params



# ============================================================================
# ABSTRACT STEPS (Towering concepts of event processing)
# ============================================================================

class FilterStep(ExecutableModel, ABC):
    """Abstract concept: Filtering/searching for objects"""
    sources: List[Source]
    time_context: Optional[TimeContext] = Field(default_factory=TimeContext)
    
    @abstractmethod
    def execute(self, context: ExecutionContext, result: IRResult) -> None:
        pass


class EnrichStep(ExecutableModel, ABC):
    """Abstract concept: Enriching data with additional information"""
    sources: List[Source]
    object_id: Optional[str] = None
    time_context: Optional[TimeContext] = Field(default_factory=TimeContext)
    
    @abstractmethod
    def execute(self, context: ExecutionContext, result: IRResult) -> None:
        pass


class AnalyzeStep(ExecutableModel, ABC):
    """Abstract concept: Analyzing/classifying objects"""
    sources: List[Source]
    object_id: Optional[str] = None
    time_context: Optional[TimeContext] = Field(default_factory=TimeContext)
    
    @abstractmethod
    def execute(self, context: ExecutionContext, result: IRResult) -> None:
        pass


class MonitorStep(ExecutableModel, ABC):
    """Abstract concept: Monitoring real-time streams"""
    sources: List[Source]
    time_context: Optional[TimeContext] = Field(default_factory=TimeContext)
    
    @abstractmethod
    def execute(self, context: ExecutionContext, result: IRResult) -> None:
        pass


class ActStep(ExecutableModel, ABC):
    """Abstract concept: Taking actions"""
    sources: List[Source]
    time_context: Optional[TimeContext] = Field(default_factory=TimeContext)
    
    @abstractmethod
    def execute(self, context: ExecutionContext, result: IRResult) -> None:
        pass


# ============================================================================
# CONCRETE FILTER IMPLEMENTATIONS
# Each checks exactly ONE capability
# ============================================================================

class FindObjectStep(FilterStep):
    """Find single object by ID"""
    object_id: str
    
    # Each concrete model has exactly ONE capability requirement
    capability: Capability = Capability.OBJECT_QUERY
    
    def execute(self, context: ExecutionContext, result: IRResult) -> None:
        for src in self.sources:
            broker = context.get_broker(src.broker)
            name = broker.name.lower()

            # This model ONLY uses object_query
            data = broker.object_query(self.object_id)
            result.find_results[name] = data

        # Set object_id in context if not set
        if not context.object_id:
            context.object_id = self.object_id


class FindObjectsStep(FilterStep):
    """Find multiple objects by criteria"""
    criteria: Dict[str, Any]  # e.g., {"mag_lt": 18, "ra": 123.4, "dec": -45.6}
    
    capability: Capability = Capability.OBJECTS_QUERY
    
    def execute(self, context: ExecutionContext, result: IRResult) -> None:
        for src in self.sources:
            broker = context.get_broker(src.broker)
            name = broker.name.lower()
            
            data = broker.objects_query(self.criteria)
            # For multiple objects, we might want to store differently
            result.find_results[f"{name}_multiple"] = data


class ConeSearchStep(FilterStep):
    """Search by cone (RA, Dec, radius)"""
    ra: float
    dec: float
    radius: float
    mag_limit: Optional[float] = None
    
    capability: Capability = Capability.CONESEARCH
    
    def execute(self, context: ExecutionContext, result: IRResult) -> None:
        for src in self.sources:
            broker = context.get_broker(src.broker)
            name = broker.name.lower()
            
            data = broker.cone_search(
                ra=self.ra, 
                dec=self.dec, 
                radius=self.radius,
                mag_limit=self.mag_limit
            )
            result.find_results[f"{name}_cone"] = data


class SqlQueryStep(FilterStep):
    """SQL-style query"""
    query: str
    
    capability: Capability = Capability.SQL_QUERY
    
    def execute(self, context: ExecutionContext, result: IRResult) -> None:
        for src in self.sources:
            broker = context.get_broker(src.broker)
            name = broker.name.lower()
            
            data = broker.sql_query(self.query)
            result.filter_results.setdefault(name, []).append(data)


# ============================================================================
# CONCRETE ENRICH IMPLEMENTATIONS
# ============================================================================

class LightcurveStep(EnrichStep):
    """Get lightcurve data"""
    band: Optional[List[str]] = None
    include_detections: bool = True
    include_non_detections: bool = False
    
    capability: Capability = Capability.LIGHTCURVE
    
    def execute(self, context: ExecutionContext, result: IRResult) -> None:
        oid = self.object_id or context.object_id
        if not oid:
            raise ValueError("No object_id provided for lightcurve")

        for src in self.sources:
            broker = context.get_broker(src.broker)
            name = broker.name.lower()
            
            #data = broker.lightcurve(oid, band=self.band)
            data = broker.lightcurve(oid)
            result.lightcurves[name] = data


class CrossmatchStep(EnrichStep):
    """Crossmatch with catalogs"""
    with_catalog: str = "gaia"
    radius: float = 1.5
    
    capability: Capability = Capability.CROSSMATCH
    
    def execute(self, context: ExecutionContext, result: IRResult) -> None:
        oid = self.object_id or context.object_id
        if not oid:
            raise ValueError("No object_id provided for crossmatch")

        for src in self.sources:
            broker = context.get_broker(src.broker)
            name = broker.name.lower()
            
            data = broker.crossmatch(oid, catalog=self.with_catalog, radius=self.radius)
            result.crossmatch_results[name] = data


class CutoutStep(EnrichStep):
    """Get image cutout"""
    format: str = "png"
    size: Optional[int] = None  # size in pixels
    
    capability: Capability = Capability.CUTOUT
    
    def execute(self, context: ExecutionContext, result: IRResult) -> None:
        oid = self.object_id or context.object_id
        if not oid:
            raise ValueError("No object_id provided for cutout")

        for src in self.sources:
            broker = context.get_broker(src.broker)
            name = broker.name.lower()
            
            data = broker.cutout(oid, format=self.format, size=self.size)
            # You might want to add cutout_results to IRResult
            # For now, store in a generic way
            result.lightcurves[f"{name}_cutout"] = data  # Temporary


# ============================================================================
# CONCRETE ANALYZE IMPLEMENTATIONS
# ============================================================================

class ClassifyStep(AnalyzeStep):
    """Classify object"""
    method: Optional[str] = None
    
    capability: Capability = Capability.CLASSIFY
    
    def execute(self, context: ExecutionContext, result: IRResult) -> None:
        oid = self.object_id or context.object_id
        if not oid:
            raise ValueError("No object_id provided for classification")

        for src in self.sources:
            broker = context.get_broker(src.broker)
            name = broker.name.lower()
            
            data = broker.classify(oid, method=self.method)
            result.classify_results.setdefault(name, []).append(data)


# Future analyze implementations:
# class SimilaritySearch(AnalyzeConcept): ...
# class PeriodicityAnalysis(AnalyzeConcept): ...
# class OutlierDetection(AnalyzeConcept): ...


# ============================================================================
# CONCRETE MONITOR IMPLEMENTATIONS
# ============================================================================

class KafkaStep(MonitorStep):
    """Monitor Kafka stream"""
    topic: Optional[str] = None
    filter: Optional[str] = None
    
    capability: Capability = Capability.KAFKA_STREAM
    
    def execute(self, context: ExecutionContext, result: IRResult) -> None:
        for src in self.sources:
            broker = context.get_broker(src.broker)
            name = broker.name.lower()
            
            if hasattr(broker, "is_kafka_monitored"):
                status = broker.is_kafka_monitored(topic=self.topic, filter=self.filter)
            else:
                status = False
            
            result.kafka_results[name] = status



# ============================================================================
# CONCRETE ACT IMPLEMENTATIONS
# ============================================================================

class EmailStep(ActStep):
    """Send email"""
    to: str
    subject: str
    body: str
    
    def execute(self, context: ExecutionContext, result: IRResult) -> None:
        for src in self.sources:
            broker = context.get_broker(src.broker)
            name = broker.name.lower()
            
            if hasattr(broker, "send_email"):
                data = broker.send_email(to=self.to, subject=self.subject, body=self.body)
            else:
                data = {"status": "not_implemented", "action": "email"}
            
            result.act_results.setdefault(name, []).append(data)


class SlackStep(ActStep):
    """Send Slack message"""
    channel: str
    message: str
    
    def execute(self, context: ExecutionContext, result: IRResult) -> None:
        for src in self.sources:
            broker = context.get_broker(src.broker)
            name = broker.name.lower()
            
            if hasattr(broker, "send_slack"):
                data = broker.send_slack(channel=self.channel, message=self.message)
            else:
                data = {"status": "not_implemented", "action": "slack"}
            
            result.act_results.setdefault(name, []).append(data)


class SaveToFileStep(ActStep):
    """Save results to file"""
    filename: str
    format: Literal["json", "csv", "txt"] = "json"
    
    def execute(self, context: ExecutionContext, result: IRResult) -> None:
        # This might not need a broker - could be local action
        import json
        import csv
        from pathlib import Path
        
        path = Path(self.filename)
        
        if self.format == "json":
            with open(path, 'w') as f:
                json.dump(result.dict(), f, indent=2)
        elif self.format == "csv":
            # Simplified - would need proper flattening
            with open(path, 'w') as f:
                writer = csv.writer(f)
                writer.writerow(["key", "value"])
                for k, v in result.dict().items():
                    writer.writerow([k, str(v)])
        
        # Store result in act_results
        for src in self.sources:
            name = src.broker.lower()
            result.act_results.setdefault(name, []).append({
                "action": "save_to_file",
                "filename": str(path),
                "format": self.format
            })


# ============================================================================
# AGGREGATE - Using TimeContext
# ============================================================================

class AggregateFunction(str, Enum):
    COUNT = "count"
    MEAN = "mean"
    MEDIAN = "median"
    STDDEV = "stddev"
    MIN = "min"
    MAX = "max"
    SUM = "sum"
    RATE = "rate"  # events per time unit
    TREND = "trend"  # linear trend coefficient

class AggregateStep(AnalyzeStep):
    """Aggregate data over time or other dimensions"""
    function: AggregateFunction
    group_by: Optional[List[str]] = None
    field: Optional[str] = None  # Which field to aggregate
    
    def execute(self, context: ExecutionContext, result: IRResult) -> None:
        oid = self.object_id or context.object_id
        
        # Get data to aggregate - either from context or fetch fresh
        data = None
        if oid and self.sources:
            for src in self.sources:
                broker = context.get_broker(src.broker)
                name = broker.name.lower()
                
                # Pass time context to lightcurve query
                query_params = {}
                if self.time_context:
                    query_params = self.time_context.apply_to_query(query_params)
                
                data = broker.lightcurve(oid, **query_params)
                if data:
                    break
        
        if not data:
            data = context.get("last_lightcurve")
        
        if not data:
            result.analyze_results.setdefault("aggregate", []).append({
                "error": "No data to aggregate",
                "time_context": self.time_context.dict() if self.time_context else None
            })
            return
        
        # Perform aggregation
        import statistics
        import numpy as np
        from scipy import stats  # for trend
        
        values = []
        timestamps = []
        
        if "detections" in data:
            for det in data["detections"]:
                if self.field and self.field in det:
                    values.append(det[self.field])
                    if "mjd" in det:
                        timestamps.append(det["mjd"])
                elif "mag" in det:
                    values.append(det["mag"])
                    if "mjd" in det:
                        timestamps.append(det["mjd"])
        
        if not values:
            result.analyze_results.setdefault("aggregate", []).append({
                "function": self.function,
                "result": None,
                "note": "No numeric values found",
                "count": 0
            })
            return
        
        agg_result = None
        metadata = {}
        
        if self.function == AggregateFunction.COUNT:
            agg_result = len(values)
        elif self.function == AggregateFunction.MEAN:
            agg_result = statistics.mean(values)
        elif self.function == AggregateFunction.MEDIAN:
            agg_result = statistics.median(values)
        elif self.function == AggregateFunction.STDDEV:
            agg_result = statistics.stdev(values) if len(values) > 1 else 0
        elif self.function == AggregateFunction.MIN:
            agg_result = min(values)
        elif self.function == AggregateFunction.MAX:
            agg_result = max(values)
        elif self.function == AggregateFunction.SUM:
            agg_result = sum(values)
        elif self.function == AggregateFunction.RATE:
            if timestamps and len(timestamps) > 1:
                time_span = max(timestamps) - min(timestamps)
                if time_span > 0:
                    agg_result = len(values) / time_span  # events per MJD
                    metadata["time_span_days"] = time_span
        elif self.function == AggregateFunction.TREND:
            if timestamps and len(timestamps) > 1:
                # Linear regression
                slope, intercept, r_value, p_value, std_err = stats.linregress(timestamps, values)
                agg_result = slope
                metadata.update({
                    "intercept": intercept,
                    "r_squared": r_value**2,
                    "p_value": p_value,
                    "std_err": std_err
                })
        
        # Add time context info to result
        time_info = {}
        if self.time_context:
            start, end = self.time_context.get_time_range()
            time_info = {
                "window": str(self.time_context.window) if self.time_context.window else None,
                "start": start.isoformat() if start else None,
                "end": end.isoformat() if end else None,
                "sampling": self.time_context.sampling
            }
        
        result.analyze_results.setdefault("aggregate", []).append({
            "function": self.function,
            "result": agg_result,
            "count": len(values),
            "time_context": time_info,
            "metadata": metadata
        })


# ============================================================================
# DERIVED STEPS
# ============================================================================

class ConfirmationStep(ExecutableModel):
    """Confirm object exists in multiple brokers"""
    object_id: str
    sources: List[Source]
    required_agreement: int = 2
    
    # This uses object_query capability
    capability: Capability = Capability.OBJECT_QUERY

    def execute(self, context: ExecutionContext, result: IRResult) -> None:
        agreement = 0

        for src in self.sources:
            broker = context.get_broker(src.broker)
            name = broker.name.lower()

            data = broker.object_query(self.object_id)
            if data:
                agreement += 1
                result.object_snapshots[name] = data

        context.set("confirm_agreement", agreement)
        context.set("confirm_success", agreement >= self.required_agreement)

        if not context.object_id:
            context.object_id = self.object_id


# ============================================================================
# 11. WORKFLOW IR
# ============================================================================

class WorkflowIR(BaseModel):
    """Workflow container - steps in execution order"""
    name: str
    steps: List[ExecutableModel] = Field(default_factory=list)
"""
    # Helper properties for backward compatibility
    @property
    def confirm(self) -> Optional[ConfirmationRule]:
        return next((s for s in self.steps if isinstance(s, ConfirmationRule)), None)

    @property
    def findobject(self) -> Optional[FindObject]:
        return next((s for s in self.steps if isinstance(s, FindObject)), None)

    @property
    def filter(self) -> List[FilterCondition]:
        return [s for s in self.steps if isinstance(s, FilterCondition)]

    @property
    def classify(self) -> List[Classifier]:
        return [s for s in self.steps if isinstance(s, Classifier)]

    @property
    def act(self) -> List[ActStep]:
        return [s for s in self.steps if isinstance(s, ActStep)]
"""
