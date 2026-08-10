# alertissimo/dsl/autocomplete.py
from lark import UnexpectedInput
from .parser import parser
from .transformer import DSL_MAPPING, FIELD_ALIASES
from alertissimo.data_layer.runtime.load import BROKER_REGISTRY


def get_autocomplete_suggestions(text: str):

    try:
        parser.parse(text)
        return []

    except UnexpectedInput as e:

        suggestions = []

        for expected in e.expected:

            if expected == "VERB":
                suggestions.extend(DSL_MAPPING.keys())

            elif expected == "KEY":
                suggestions.extend(FIELD_ALIASES.keys())
                suggestions.extend(["object_id", "sources", "required"])

            elif expected == "IDENTIFIER":
                suggestions.extend(BROKER_REGISTRY.keys())

        return sorted(set(suggestions))
