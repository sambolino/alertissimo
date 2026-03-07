from typing import List
from pydantic import BaseModel

from .parser import parse
from .transformer import DSLTransformer
from alertissimo.core.brokers.registry.load import BROKER_REGISTRY

class DSLParseError(Exception):
    pass

def parse_dsl_script(script: str):

    try:
        tree = parse(script)

        transformer = DSLTransformer()

        steps = transformer.transform(tree)

        flat = []

        # this actually flattens out the list of lists, not the transformer functions!!
        # that should be fixed properly in the final model
        for s in steps:
            if isinstance(s, list):
                flat.extend(s)
            else:
                flat.append(s)

    except Exception as e:
        raise DSLParseError(str(e))

    return flat

def validate_capabilities(step: BaseModel):

    errors = []

    required = getattr(step, "required", None)
    sources = getattr(step, "sources", None)

    if not required:
        return errors

    if not sources:
        errors.append("Missing sources definition.")
        return errors

    for src in sources:

        broker_name = src.broker
        broker_caps = BROKER_REGISTRY.get(broker_name)

        if not broker_caps:
            errors.append(f"Unknown broker: {broker_name}")
            continue

        cap_names = [cap.value for cap in broker_caps]

        if not required.matches(cap_names):
            errors.append(f"{broker_name} lacks required capability: {required}")

    return errors
