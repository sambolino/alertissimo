# alertissimo/dsl/definitions.py
"""
Central definitions for DSL verbs and their mappings to step models.
This is the SINGLE SOURCE OF TRUTH for what verbs exist and what they map to.
NO grammar generation code here - that belongs in grammar_tools.py
"""

from typing import Dict, List, Optional, Union, Any, Set
from difflib import get_close_matches

from alertissimo.core.schema import (
    # Filter steps
    FindObjectStep,
    FindObjectsStep,
    ConeSearchStep,
    SqlQueryStep,
    
    # Enrich steps
    LightcurveStep,
    CrossmatchStep,
    CutoutStep,
    
    # Analyze steps
    ClassifyStep,
    AggregateStep,
    
    # Monitor steps
    KafkaStep,
    
    # Act steps
    EmailStep,
    SlackStep,
    SaveToFileStep,
    
    # Special
    ConfirmationStep,
    
    # Base
    ExecutableModel,
    Source,
)

from alertissimo.core.brokers.registry.load import ALL_BROKERS


# ============================================================================
# 1. DIRECT MAPPING (specific verbs → concrete steps)
# ============================================================================

DIRECT_VERB_MAPPING: Dict[str, type[ExecutableModel]] = {
    # Filter/Find variants
    "findobject": FindObjectStep,
    "findobjects": FindObjectsStep,
    "conesearch": ConeSearchStep,
    "sqlquery": SqlQueryStep,
    
    # Enrich variants
    "lightcurve": LightcurveStep,
    "crossmatch": CrossmatchStep,
    "cutout": CutoutStep,
    
    # Analyze variants
    "classify": ClassifyStep,
    "aggregate": AggregateStep,
    
    # Monitor variants
    "monitor": KafkaStep,
    "kafka": KafkaStep,
    "stream": KafkaStep,
    
    # Act variants
    "email": EmailStep,
    "slack": SlackStep,
    "save": SaveToFileStep,
    
    # Special
    "confirm": ConfirmationStep,
}


# ============================================================================
# 2. GENERIC VERB RESOLUTION (based on arguments)
# ============================================================================

class VerbResolver:
    """Resolves generic verbs to specific step classes based on arguments"""
    
    def __init__(self):
        # Define resolution rules for each generic verb
        self.resolution_rules = {
            "find": self._resolve_find,
            "filter": self._resolve_find,
            "search": self._resolve_find,
            "get": self._resolve_enrich,
            "enrich": self._resolve_enrich,
            "analyze": self._resolve_analyze,
            "process": self._resolve_analyze,
            "monitor": self._resolve_monitor,
            "watch": self._resolve_monitor,
            "act": self._resolve_act,
            "do": self._resolve_act,
            "send": self._resolve_act,
            "notify": self._resolve_act,
        }
    
    def resolve(self, verb: str, args: Dict[str, Any]) -> type[ExecutableModel]:
        """Resolve a generic verb to a step class based on arguments"""
        resolver = self.resolution_rules.get(verb.lower())
        if resolver:
            return resolver(args)
        
        # If no resolver, try direct mapping as fallback
        if verb in DIRECT_VERB_MAPPING:
            return DIRECT_VERB_MAPPING[verb]
        
        # Unknown verb - generate helpful suggestions
        suggestions = get_close_matches(
            verb, 
            list(DIRECT_VERB_MAPPING.keys()) + list(self.resolution_rules.keys()),
            n=3
        )
        if suggestions:
            raise ValueError(f"Unknown verb '{verb}'. Did you mean: {', '.join(suggestions)}?")
        else:
            raise ValueError(f"Unknown verb '{verb}'. No similar verbs found.")
    
    def _resolve_find(self, args: Dict[str, Any]) -> type[ExecutableModel]:
        """Resolve 'find' to appropriate step based on arguments"""
        if "object_id" in args and len(args) <= 3:  # object_id + sources + maybe time_context
            return FindObjectStep
        elif "ra" in args and "dec" in args and "radius" in args:
            return ConeSearchStep
        elif "query" in args or "sql" in args:
            return SqlQueryStep
        elif "criteria" in args or any(k.startswith(("mag_", "ndet_", "min_", "max_")) for k in args.keys()):
            return FindObjectsStep
    
    def _resolve_enrich(self, args: Dict[str, Any]) -> type[ExecutableModel]:
        """Resolve 'enrich' to appropriate step based on arguments"""
        if "band" in args:
            return LightcurveStep
        elif "catalog" in args or "with" in args:
            return CrossmatchStep
        elif "format" in args or "cutout" in str(args):
            return CutoutStep
        else:
            # Default to lightcurve (most common)
            return LightcurveStep
    
    def _resolve_analyze(self, args: Dict[str, Any]) -> type[ExecutableModel]:
        """Resolve 'analyze' to appropriate step based on arguments"""
        if "function" in args or any(k in args for k in ["aggregate", "stats", "mean", "median", "count"]):
            return AggregateStep
        else:
            return ClassifyStep
    
    def _resolve_monitor(self, args: Dict[str, Any]) -> type[ExecutableModel]:
        """Resolve 'monitor' to appropriate step"""
        # Only Kafka for now, but could have more in future
        return KafkaStep
    
    def _resolve_act(self, args: Dict[str, Any]) -> type[ExecutableModel]:
        """Resolve 'act' to appropriate step based on arguments"""
        if "email" in args or "to" in args:
            return EmailStep
        elif "slack" in args or "channel" in args:
            return SlackStep
        elif "filename" in args or "file" in args:
            return SaveToFileStep


# Singleton resolver instance
_resolver = VerbResolver()


# ============================================================================
# 3. FIELD ALIASES (user-friendly parameter names)
# ============================================================================

FIELD_ALIASES = {
    # source → sources
    "source": "sources",
    "src": "sources",
    "broker": "sources",
    "brokers": "sources",
    "from": "sources",
    
    # object_id aliases
    "id": "object_id",
    "obj": "object_id",
    "oid": "object_id",
    "target": "object_id",
    
    # catalog aliases
    "catalog": "with_catalog",
    "cat": "with_catalog",
    
    # format aliases
    "fmt": "format",
    
    # radius aliases
    "rad": "radius",
    "r": "radius",
    
    # band aliases
    "bands": "band",
    "filter": "band",
    "filters": "band",
}


# ============================================================================
# 4. MAIN RESOLUTION FUNCTION
# ============================================================================

def get_step_class(verb: str, args: Dict[str, Any]) -> type[ExecutableModel]:
    """
    Main entry point for resolving a verb to a step class.
    
    Priority:
    1. Direct mapping (user was explicit)
    2. Generic resolution (infer from arguments)
    """
    verb = verb.lower()
    
    # Try direct mapping first
    if verb in DIRECT_VERB_MAPPING:
        return DIRECT_VERB_MAPPING[verb]
    
    # Try generic resolution
    try:
        return _resolver.resolve(verb, args)
    except ValueError as e:
        # Re-raise with line number info (added by caller)
        raise ValueError(str(e))


# ============================================================================
# 5. DSLParseError (for parsing errors)
# ============================================================================

class DSLParseError(Exception):
    """Exception raised for DSL parsing errors with line numbers and suggestions"""
    def __init__(self, message: str, line: int = None, token: str = None, candidates: List[str] = None):
        self.message = message
        self.line = line
        self.token = token
        self.candidates = candidates or []
        super().__init__(self.__str__())
    
    def __str__(self):
        msg = self.message
        if self.line:
            msg = f"Line {self.line}: {msg}"
        if self.token and self.candidates:
            suggestion = get_close_matches(self.token, self.candidates, n=1)
            if suggestion:
                msg += f"\nDid you mean '{suggestion[0]}'?"
        return msg


# ============================================================================
# 6. EXPORT VERB LIST (for grammar generation)
# ============================================================================

def get_all_verbs() -> List[str]:
    """Return all known verbs (both direct and generic + common aliases)"""
    verbs: Set[str] = set()
    
    # Add all direct mapping verbs
    verbs.update(DIRECT_VERB_MAPPING.keys())
    
    # Add all generic resolution verbs
    verbs.update(_resolver.resolution_rules.keys())
    
    # Add common aliases that might not be in mappings
    common_aliases = {
        "cone", "near",           # conesearch aliases
        "lc", "timeseries",       # lightcurve aliases
        "xm", "match",            # crossmatch aliases
        "class",                   # classify alias
        "stats", "summarize",      # aggregate aliases
        "watch",                   # monitor alias
        "mail",                    # email alias
        "write", "export",         # save alias
    }
    verbs.update(common_aliases)
    
    return sorted(list(verbs))


def get_verbs_for_step(step_class: type[ExecutableModel]) -> List[str]:
    """Return all verbs that can produce this step class"""
    verbs = []
    for verb, cls in DIRECT_VERB_MAPPING.items():
        if cls == step_class:
            verbs.append(verb)
    return verbs


# ============================================================================
# 7. VALIDATION HELPERS
# ============================================================================

def validate_step_against_capabilities(step: ExecutableModel) -> List[str]:
    """
    Validate that all sources in a step support the required capability.
    Returns list of error messages (empty if valid).
    """
    errors = []
    
    # Get required capability from step (if it has one)
    required = getattr(step, 'required_capability', None)
    if not required:
        return errors
    
    # Get sources
    sources = getattr(step, 'sources', [])
    if not sources:
        return errors
    
    # Import here to avoid circular imports
    from alertissimo.core.brokers.registry.load import BROKER_REGISTRY
    
    for source in sources:
        broker_name = source.broker
        broker_caps = BROKER_REGISTRY.get(broker_name, [])
        
        if not broker_caps:
            errors.append(f"Unknown broker: {broker_name}")
            continue
        
        # Check if capability exists in broker's capabilities
        cap_names = [cap.value for cap in broker_caps]
        if required not in cap_names:
            errors.append(
                f"{broker_name} does not support '{required}'. "
                f"Supports: {', '.join(cap_names)}"
            )
    
    return errors
