from lark import Transformer
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
    Source
)

from alertissimo.core.brokers.registry.load import ALL_BROKERS


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

FIELD_ALIASES = {
    "source": "sources",
    "src": "sources",
    "broker": "sources",
}


class DSLTransformer(Transformer):

    def STRING(self, s):
        return s[1:-1]

    def NUMBER(self, n):
        n = str(n)
        if "." in n:
            return float(n)
        return int(n)

    def true(self, _):
        return True

    def false(self, _):
        return False

    def IDENTIFIER(self, v):
        return str(v)

    def list(self, items):
        return list(items)

    def parameter(self, items):
        key = str(items[0])
        value = items[1]

        key = FIELD_ALIASES.get(key, key)

        if key == "sources":

            # value is list
            if isinstance(value, list):

                if "all" in value:
                    return (key, [Source(broker=b) for b in ALL_BROKERS])

                return (key, [Source(broker=v) for v in value])

            # value is single
            if value == "all":
                return (key, [Source(broker=b) for b in ALL_BROKERS])

            return (key, [Source(broker=value)])

        return (key, value)

    def start(self, items):
        return items

    def script(self, items):
        flat = []
        for item in items:
            if isinstance(item, list):
                flat.extend(item)
            else:
                flat.append(item)
        return flat

    def statement(self, items):
        item = items[0]
        if isinstance(item, list):
            return item[0]
        return item

    def simple_command(self, items):

        verb = str(items[0])
        params = dict(items[1:])

        model_cls = DSL_MAPPING.get(verb)

        if not model_cls:
            raise ValueError(f"Unknown DSL verb: {verb}")

        return model_cls(**params)

    def VERB(self, v):
        return str(v)

    def KEY(self, k):
        return str(k)
