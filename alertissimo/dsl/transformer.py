# alertissimo/dsl/transformer.py
from lark import Transformer
from typing import List
from difflib import get_close_matches

from alertissimo.core.schema import (
    FindObject,
    Classifier,
    LightcurveStep,
    CrossmatchStep,
    CutoutStep,
    KafkaStep,
    ConfirmationRule,
    ScoringRule,
    ActStep,
    Source,
)
from alertissimo.core.brokers.registry.load import ALL_BROKERS

# Map DSL verbs to Pydantic models
DSL_MAPPING = {
    "find": FindObject,
    "classify": Classifier,
    "lightcurve": LightcurveStep,
    "crossmatch": CrossmatchStep,
    "cutout": CutoutStep,
    "monitor": KafkaStep,
    "confirm": ConfirmationRule,
    "score": ScoringRule,
    "act": ActStep,
}

# Field aliases for user-friendly DSL
FIELD_ALIASES = {
    "source": "sources",
    "src": "sources",
    "broker": "sources",
    "brokers": "sources",
}

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


class DSLTransformer(Transformer):
    """Transforms Lark parse Tree into a flat list of Pydantic models"""

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
        """
        Rekurzivno flattenovanje koje radi sa svim nivoima ugnježdenja.
        Ovo je ključna funkcija koja rešava tvoj problem.
        """
        flat = []
        for x in items:
            if isinstance(x, (list, tuple)):
                flat.extend(self._flatten(x))
            elif x is not None:  # Ignoriši None vrednosti
                flat.append(x)
        return flat

    '''
    def _flatten(self, items):
        flat = []
        for x in items:
            if isinstance(x, list):
                flat.extend(self._flatten(x))
            else:
                flat.append(x)
        return flat
    '''
    # -----------------------------
    # Parameters
    # -----------------------------

    def parameter(self, items):
        key = str(items[0])
        value = items[1]

        key = FIELD_ALIASES.get(key, key)

        if key == "sources":

            if isinstance(value, list):
                if "all" in value:
                    return key, [Source(broker=b) for b in ALL_BROKERS]
                return key, [Source(broker=v) for v in value]

            if value == "all":
                return key, [Source(broker=b) for b in ALL_BROKERS]

            return key, [Source(broker=value)]

        return key, value

    # -----------------------------
    # Commands
    # -----------------------------

    def simple_command(self, items):

        verb = str(items[0])
        params = dict(items[1:])

        model_cls = DSL_MAPPING.get(verb)

        if not model_cls:
            raise DSLParseError(
                f"Unknown DSL verb: {verb}",
                token=verb,
                candidates=list(DSL_MAPPING.keys())
            )

        try:
            return model_cls(**params)
        except Exception as e:
            raise DSLParseError(f"Failed to create model for '{verb}': {e}")

    # -----------------------------
    # Grammar structure
    # -----------------------------

    def statement(self, items):
        return self._flatten(items)

    def script(self, items):
        return self._flatten(items)

    def start(self, items):
        return self._flatten(items)
    
    '''
    #keep this for debugging if needed
    #transfermer takes one line at a time, thats why we later get list of lists
    #that should be fine and final flattening should be done in parse_dsl_script
    
    def start(self, items):
        print(f"🔥 start ulaz: {len(items)} items")
        for i, item in enumerate(items):
            print(f"  [{i}] {type(item).__name__}")
            if isinstance(item, list):
                print(f"    list dužina: {len(item)}")

        result = self._flatten(items)
        print(f"✅ start izlaz: {len(result)} items")
        for i, item in enumerate(result):
            print(f"  [{i}] {type(item).__name__}")

        return result
    '''
