# alertissimo/dsl/grammar_tools.py
"""
Tools for generating and validating grammar.lark from definitions.py
Run with: python -m alertissimo.dsl.grammar_tools --generate
          python -m alertissimo.dsl.grammar_tools --validate
"""

import re
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Optional

from alertissimo.dsl.definitions import get_all_verbs

# alertissimo/dsl/grammar_tools.py

def generate_grammar(output_path: Optional[str] = None) -> str:
    """
    Generate Lark grammar file content based on working version.
    Comments are IGNORED, not parsed as statements.
    """
    verbs = get_all_verbs()

    # Format verbs as a Lark alternation
    verb_lines = "\n    | ".join(f'"{v}"' for v in verbs)

    grammar = f"""// AUTO-GENERATED FROM definitions.py - DO NOT EDIT DIRECTLY
// Generated: {datetime.now().isoformat()}
// Source: alertissimo/dsl/definitions.py
// Total verbs: {len(verbs)}

start: script

script: (statement NEWLINE*)+

statement: simple_command NEWLINE*

simple_command: VERB parameter*

parameter: KEY "=" value

?value: STRING
      | NUMBER
      | IDENTIFIER
      | list
      | geometry
      | TRUE
      | FALSE

list: "[" [value ("," value)*] "]"

geometry: point
        | circle
        | box
        | polygon

point: "point(" NUMBER "," NUMBER ")"
circle: "circle(" NUMBER "," NUMBER "," NUMBER ")"
box: "box(" NUMBER "," NUMBER "," NUMBER "," NUMBER ")"
polygon: "polygon(" NUMBER "," NUMBER ("," NUMBER "," NUMBER)+ ")"

VERB: {verb_lines}

KEY: /[a-zA-Z_][a-zA-Z0-9_]*/

IDENTIFIER: /[A-Za-z0-9_\\-\\.]+/

TRUE: "true"
FALSE: "false"

COMMENT: /#[^\\n]*/

STRING: ESCAPED_STRING
NUMBER: SIGNED_NUMBER

%import common.ESCAPED_STRING
%import common.SIGNED_NUMBER
%import common.NEWLINE
%import common.WS_INLINE

%ignore WS_INLINE
%ignore COMMENT
"""

    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            f.write(grammar)
        print(f"✅ Grammar generated at {output_path}")
        print(f"   with {len(verbs)} verbs")

    return grammar


def validate_grammar(grammar_path: Optional[str] = None) -> bool:
    """
    Validate that grammar.lark matches definitions.py
    Returns True if valid, False otherwise.
    """
    if grammar_path is None:
        grammar_path = Path(__file__).parent / "grammar.lark"
    else:
        grammar_path = Path(grammar_path)
    
    if not grammar_path.exists():
        print(f"❌ Grammar file not found: {grammar_path}")
        print("   Run: python -m alertissimo.dsl.grammar_tools --generate")
        return False
    
    # Get verbs from definitions
    def_verbs = set(get_all_verbs())
    
    # Extract verbs from grammar
    with open(grammar_path) as f:
        grammar = f.read()
    
    verb_match = re.search(r'VERB: (.*?)\n', grammar)
    if not verb_match:
        print("❌ Could not find VERB definition in grammar")
        return False
    
    grammar_verbs_str = verb_match.group(1)
    
    # Parse quoted verbs
    grammar_verbs = set()
    for match in re.finditer(r'"([^"]+)"', grammar_verbs_str):
        grammar_verbs.add(match.group(1))
    
    # Check for missing verbs
    missing = def_verbs - grammar_verbs
    extra = grammar_verbs - def_verbs
    
    if missing:
        print(f"❌ Grammar missing {len(missing)} verbs:")
        for v in sorted(missing)[:10]:
            print(f"   - {v}")
        if len(missing) > 10:
            print(f"   ... and {len(missing)-10} more")
    
    if extra:
        print(f"⚠️ Grammar has {len(extra)} extra verbs (not in definitions):")
        for v in sorted(extra)[:5]:
            print(f"   - {v}")
        if len(extra) > 5:
            print(f"   ... and {len(extra)-5} more")
    
    if not missing and not extra:
        print(f"✅ Grammar valid with {len(grammar_verbs)} verbs")
        return True
    
    return False


def main():
    """Command-line interface"""
    parser = argparse.ArgumentParser(description="DSL Grammar Tools")
    parser.add_argument('--generate', '-g', action='store_true', 
                       help='Generate grammar.lark from definitions')
    parser.add_argument('--validate', '-v', action='store_true',
                       help='Validate grammar.lark against definitions')
    parser.add_argument('--output', '-o', type=str, default=None,
                       help='Output path for generated grammar (default: grammar.lark in same dir)')
    
    args = parser.parse_args()
    
    if args.generate:
        if args.output:
            generate_grammar(args.output)
        else:
            # Default to grammar.lark in same directory as this script
            default_path = Path(__file__).parent / "grammar.lark"
            generate_grammar(str(default_path))
    
    if args.validate:
        if args.output:
            success = validate_grammar(args.output)
        else:
            default_path = Path(__file__).parent / "grammar.lark"
            success = validate_grammar(str(default_path))
        sys.exit(0 if success else 1)
    
    if not args.generate and not args.validate:
        parser.print_help()


if __name__ == "__main__":
    main()
