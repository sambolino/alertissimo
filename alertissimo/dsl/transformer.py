# alertissimo/dsl/transformer.py

from lark import Transformer
from typing import Any, Dict, List

from alertissimo.core.schema import Source
from alertissimo.data_layer.runtime.load import ALL_BROKERS
from alertissimo.dsl.definitions import (
    get_step_class,
    FIELD_ALIASES,
    DSLParseError,
    get_all_verbs,
)


class DSLTransformer(Transformer):
    """Transforms Lark parse Tree into Pydantic models using definitions.py"""
    
    # -----------------------------
    # Primitive conversions
    # -----------------------------
    
    def STRING(self, s):
        return s[1:-1]
    
    def NUMBER(self, n):
        n = str(n)
        return float(n) if "." in n else int(n)
    
    def true(self, _):
        return True
    
    def false(self, _):
        return False
    
    def IDENTIFIER(self, v):
        return str(v)
    
    def KEY(self, k):
        return str(k)
    
    def VERB(self, v):
        return str(v)
    
    def list(self, items):
        return list(items)
    
    # -----------------------------
    # Utility: recursive flatten
    # -----------------------------
    
    def _flatten(self, items):
        """Recursively flatten nested structures"""
        flat = []
        for x in items:
            if isinstance(x, (list, tuple)):
                flat.extend(self._flatten(x))
            elif x is not None:
                flat.append(x)
        return flat
    
    # -----------------------------
    # Parameters
    # -----------------------------
    
    def parameter(self, items):
        """Convert a parameter key=value pair"""
        raw_key = str(items[0])
        value = items[1]
        
        # Apply field aliases
        key = FIELD_ALIASES.get(raw_key, raw_key)
        
        # Special handling for sources
        if key == "sources":
            return self._handle_sources(key, value)
        
        return key, value
    
    def _handle_sources(self, key: str, value: Any):
        """Special handling for sources parameter"""
        if isinstance(value, list):
            if "all" in value:
                return key, [Source(broker=b) for b in ALL_BROKERS]
            return key, [Source(broker=v) for v in value]
        
        if value == "all":
            return key, [Source(broker=b) for b in ALL_BROKERS]
        
        return key, [Source(broker=value)]
    
    # -----------------------------
    # Commands
    # -----------------------------
    
    def simple_command(self, items):
        """Convert a simple command to a step model"""
        verb = str(items[0])
        params = dict(items[1:])
        
        try:
            # Get the appropriate step class from definitions
            step_class = get_step_class(verb, params)
            
            # Create instance
            return step_class(**params)
            
        except ValueError as e:
            # Resolution error
            raise DSLParseError(
                message=str(e),
                token=verb,
                candidates=get_all_verbs()
            )
        except Exception as e:
            # Model creation error
            raise DSLParseError(
                message=f"Failed to create model for '{verb}': {e}",
                token=verb
            )
    
    # -----------------------------
    # Grammar structure
    # -----------------------------
    
    def statement(self, items):
        return self._flatten(items)
    
    def script(self, items):
        return self._flatten(items)
    
    def start(self, items):
        return self._flatten(items)
