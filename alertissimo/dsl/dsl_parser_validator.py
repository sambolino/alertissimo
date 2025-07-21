from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ValidationError, TypeAdapter
import shlex
from alertissimo.core.schema import (
    Capability,
    CapabilityRequirement,
    FilterCondition,
    FindObject,
    ConfirmationRule,
    Classifier,
    ScoringRule,
    ActStep,
    LightcurveStep,
    CrossmatchStep,
    CutoutStep,
    KafkaStep,
    Source
)
from alertissimo.core.brokers.registry.load import BROKER_REGISTRY, ALL_BROKERS

# DSL Verb Mapping
DSL_MAPPING = {
    "filter": FilterCondition,
    "find": FindObject,
    "confirm": ConfirmationRule,
    "classify": Classifier,
    "score": ScoringRule,
    "act": ActStep,
    "lightcurve": LightcurveStep,
    "crossmatch": CrossmatchStep,
    "cutout": CutoutStep,
    "monitor": KafkaStep,
}

# Define field aliases for more flexible DSL
FIELD_ALIASES = {
    "source": "sources",
    "src": "sources",
    "broker": "sources",
    "brokers": "sources",
    "origin": "sources",
    # Add other aliases as needed
}

# Fields that expect Source(s)
BROKER_FIELDS = {"sources"}

class DSLParseError(Exception):
    pass

def parse_dsl_line(line: str) -> BaseModel:
    parts = shlex.split(line)
    if not parts:
        raise DSLParseError("Empty line")

    verb = parts[0].lower()
    model_cls = DSL_MAPPING.get(verb)
    if not model_cls:
        raise DSLParseError(f"Unknown DSL verb: {verb}")

    args: Dict[str, Any] = {}
    i = 1
    while i < len(parts):
        part = parts[i]
        if '=' not in part:
            raise DSLParseError(f"Malformed argument: {part}")

        key, value = part.split('=', 1)
        
        # Normalize field names using aliases
        normalized_key = FIELD_ALIASES.get(key, key)

        # Handle lists that are split across tokens
        if value.startswith('[') and not value.endswith(']'):
            list_tokens = [value]
            i += 1
            while i < len(parts) and not parts[i].endswith(']'):
                list_tokens.append(parts[i])
                i += 1
            if i < len(parts):
                list_tokens.append(parts[i])
            value = ' '.join(list_tokens)

        if value.startswith('[') and value.endswith(']'):
            items = [v.strip() for v in value[1:-1].split(',') if v.strip()]

            if normalized_key in BROKER_FIELDS:
                # Handle 'all' in lists
                if 'all' in items:
                    # Replace 'all' with all broker names
                    items = ALL_BROKERS
                args[normalized_key] = [Source(broker=item) for item in items]
            else:
                args[normalized_key] = items
        else:
            if normalized_key in BROKER_FIELDS:
                # Handle 'all' for single source
                if value.lower() == 'all':
                    args[normalized_key] = [Source(broker=broker) for broker in ALL_BROKERS]
                else:
                    # For broker fields, convert to list for consistency
                    args[normalized_key] = [Source(broker=value)]
            else:
                args[normalized_key] = value.strip('"')
        i += 1

    try:
        return model_cls(**args)
    except ValidationError as e:
        raise DSLParseError(f"Validation failed for '{verb}': {e}")

def parse_dsl_script(script: str) -> List[BaseModel]:
    steps = []
    for line in script.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        step = parse_dsl_line(line)
        steps.append(step)
    return steps

# Validation Layer: checks capability requirements against broker registry
def validate_capabilities(step: BaseModel) -> List[str]:
    errors = []
    required: CapabilityRequirement | None = getattr(step, "required", None)
    sources = getattr(step, "sources", None)

    if not required:
        return errors

    if not sources:
        errors.append("Missing sources definition.")
        return errors

    # Flatten all sources into a list
    sources_list = sources if isinstance(sources, list) else [sources]

    for src in sources_list:
        if not src:
            errors.append("Invalid source definition.")
            continue

        broker_name = src.broker
        broker_caps = BROKER_REGISTRY.get(broker_name)
        if not broker_caps:
            errors.append(f"Unknown broker: {broker_name}")
            continue

        # Get capability names for this broker
        cap_names = [cap.value for cap in broker_caps]

        if not required.matches(cap_names):
            errors.append(f"{broker_name} lacks required capability: {required}")

    return errors
