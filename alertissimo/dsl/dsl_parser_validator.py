# alertissimo/dsl/dsl_parser_validator.py

from lark import Lark, UnexpectedInput
from pathlib import Path
from typing import List, Optional
import logging

from alertissimo.core.schema import ExecutableModel, IRResult, ExecutionContext
from alertissimo.data_layer.runtime.load import BROKER_REGISTRY
from alertissimo.dsl.transformer import DSLTransformer
from alertissimo.dsl.definitions import DSLParseError, get_all_verbs
from alertissimo.dsl.grammar_tools import generate_grammar, validate_grammar

logger = logging.getLogger(__name__)

# Paths
GRAMMAR_PATH = Path(__file__).parent / "grammar.lark"

# Auto-generate grammar if in development
def ensure_grammar():
    """Generate grammar if missing or outdated"""
    if not GRAMMAR_PATH.exists():
        logger.info("Grammar file missing - generating...")
        generate_grammar(str(GRAMMAR_PATH))
    elif not validate_grammar(str(GRAMMAR_PATH)):
        logger.warning("Grammar out of date - regenerating...")
        generate_grammar(str(GRAMMAR_PATH))
    else:
        logger.debug("Grammar is up to date")

# Generate on import
ensure_grammar()

# Load grammar
with open(GRAMMAR_PATH) as f:
    GRAMMAR = f.read()

# Create parser with transformer
_transformer = DSLTransformer()
_parser = Lark(GRAMMAR, parser='lalr', transformer=_transformer)


def parse_dsl_script(script: str) -> List[ExecutableModel]:
    """
    Parse DSL script into a flat list of step models.
    
    Args:
        script: DSL script string
        
    Returns:
        List of ExecutableModel instances
        
    Raises:
        DSLParseError: On parsing errors with line numbers and suggestions
    """
    if not script or not script.strip():
        return []
    
    steps = []
    
    for i, line in enumerate(script.strip().splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        
        try:
            result = _parser.parse(line)
            
            # Flatten if needed (parser returns list for multi-step lines)
            if isinstance(result, list):
                steps.extend(result)
            elif result is not None:
                steps.append(result)
                
        except UnexpectedInput as e:
            # Lark syntax error
            raise DSLParseError(
                message=f"Syntax error: {e}",
                line=i,
                token=line.split()[0] if line.split() else None,
                candidates=get_all_verbs()
            )
        except DSLParseError as e:
            # Already formatted error, just add line number
            e.line = i
            raise e
        except Exception as e:
            # Unexpected error
            raise DSLParseError(
                message=f"Unexpected error: {e}",
                line=i
            )
    
    return steps

def validate_capabilities(step: ExecutableModel) -> List[str]:
    """
    Validate that all sources in a step support the required capability.
    Returns list of error messages (empty if valid).
    """
    errors = []
    
    # Get required capability
    required = step.get_required_capability()
    if not required:
        return errors  # No capability requirement
    
    # Get sources
    sources = getattr(step, 'sources', [])
    if not sources:
        return errors
    
    for source in sources:
        broker_name = source.broker
        broker_caps = BROKER_REGISTRY.get(broker_name, [])
        
        if not broker_caps:
            errors.append(f"Unknown broker: {broker_name}")
            continue
        
        if required not in broker_caps:
            errors.append(
                f"{broker_name} does not support '{required}' "
                f"(required by {step.__class__.__name__})"
            )
    
    return errors
