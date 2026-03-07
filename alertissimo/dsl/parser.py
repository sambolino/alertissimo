# DSL parser using Lark
from lark import Lark
from pathlib import Path

GRAMMAR_PATH = Path(__file__).parent / "grammar.lark"

parser = Lark.open(
    GRAMMAR_PATH,
    parser="lalr",
    start="start"
)

def parse(script: str):
    return parser.parse(script)
