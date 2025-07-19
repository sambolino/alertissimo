from typing import Any, Dict, List
from pydantic import BaseModel, ValidationError
import shlex
import yaml
from alertissimo.core.schema import (
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
)

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
            args[key] = [v.strip() for v in value[1:-1].split(',') if v.strip()]
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

def load_broker_registry(broker_names: List[str], registry_path: str = "alertissimo/core/brokers/registry") -> Dict[str, Dict[str, Any]]:
    registry = {}
    for broker in broker_names:
        try:
            with open(f"{registry_path}/{broker}.yaml", "r") as f:
                registry[broker] = yaml.safe_load(f)
        except FileNotFoundError:
            registry[broker] = {}
    return registry

def validate_capabilities(step: BaseModel, broker_registry: Dict[str, Dict[str, Any]]) -> List[str]:
    errors = []
    required = getattr(step, "required", None)
    source = getattr(step, "source", None) or getattr(step, "sources", None)

    if not required:
        return errors

    capability_sets = required.capability_sets()
    sources = source if isinstance(source, list) else [source]

    for src in sources:
        if not src:
            errors.append("Missing source definition.")
            continue
        broker_caps = broker_registry.get(src.broker, {}).get("capabilities", [])
        if not any(set(req_set).issubset(broker_caps) for req_set in capability_sets):
            errors.append(f"{src.broker} lacks required capabilities: {capability_sets}")
    return errors

