# alertissimo/dsl/dsl_parser_validator.py
from typing import List
from pydantic import BaseModel
from .parser import parse
from .transformer import DSLTransformer, DSLParseError
from alertissimo.core.brokers.registry.load import BROKER_REGISTRY
from lark import UnexpectedInput


def parse_dsl_script(script: str) -> List[BaseModel]:
    """
    Parse a DSL script into a flat list of Pydantic step models.
    Raises DSLParseError with line numbers and suggestions.
    """
    steps: List[BaseModel] = []
    transformer = DSLTransformer()

    for i, line in enumerate(script.strip().splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            tree = parse(line)
            result = transformer.transform(tree)
            steps.append(result)

            # Flatten list-of-lists from the transformer
            if isinstance(result, list):
                steps.extend(result)
            else:
                steps.append(result)

        except UnexpectedInput as e:
            # Lark parse error
            raise DSLParseError(
                message=f"Syntax error at column {e.column}",
                line=i,
                token=line.split()[0] if line.split() else None,
                candidates=list(transformer.DSL_MAPPING.keys())
            )
        except DSLParseError as e:
            # Already a DSLTransformer error, add line number
            raise DSLParseError(message=str(e), line=i)
        except Exception as e:
            # Generic error
            raise DSLParseError(f"Line {i}: {e}")

    return steps


def validate_capabilities(step: BaseModel) -> List[str]:
    """
    Check that the given DSL step has all required capabilities in the broker registry.
    """
    errors: List[str] = []

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
