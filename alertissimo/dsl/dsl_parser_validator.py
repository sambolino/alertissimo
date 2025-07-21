from typing import Any, Dict, List
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

BROKER_FIELDS = {"source", "sources"}  # any fields expecting Source(s)

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

            if key in BROKER_FIELDS:
                # Handle 'all' in lists
                if 'all' in items:
                    # Replace 'all' with all broker names
                    items = ALL_BROKERS
                args[key] = [Source(broker=item) for item in items]
            else:
                args[key] = items
        else:
            if key in BROKER_FIELDS:
                # Handle 'all' for single source
                if value.lower() == 'all':
                    args[key] = [Source(broker=broker) for broker in ALL_BROKERS]
                else:
                    args[key] = Source(broker=value)
            else:
                args[key] = value.strip('"')
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

# Validation Layer: checks capability requirements against YAML broker registry

def validate_capabilities(step: BaseModel, broker_registry: Dict[str, List[CapabilityRequirement]]) -> List[str]:
    errors = []
    required: CapabilityRequirement | None = getattr(step, "required", None)
    source = getattr(step, "source", None) or getattr(step, "sources", None)

    if not required:
        return errors

    sources = source if isinstance(source, list) else [source]

    # Determine which brokers to validate against
    if sources and sources[0] and getattr(sources[0], 'broker', None) == 'all':
        brokers_to_check = ALL_BROKERS
    else:
        brokers_to_check = [src.broker for src in sources if src]


    for broker_name in brokers_to_check:
        if not broker_name:
            errors.append("Missing source definition.")
            continue
        
        broker_caps = broker_registry.get(broker_name)
        if not broker_caps:
            errors.append(f"Unknown broker: {broker_name}")
            continue

        # Flatten all capabilities for that broker
        all_caps = [cap for cap in broker_caps]

        # Convert them to strings to compare with CapabilityRequirement.matches
        cap_names = [cap.value if isinstance(cap, Capability) else cap for cap in all_caps]

        if not required.matches(cap_names):
            errors.append(f"{broker_name} lacks required capability: {required}")

    return errors
