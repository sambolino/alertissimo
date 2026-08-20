"""Lark-backed parser for the formal Alertissimo DSL grammar."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
import re
from typing import Literal

from lark import Lark, Transformer, UnexpectedInput
from lark.exceptions import VisitError
from lark.indenter import Indenter

from .surface import (
    AngularRadius,
    CandidateSet,
    DSLParseError,
    Duration,
    FilterClause,
    InsideClause,
    LatestClause,
    MatchClause,
    OrderByClause,
    RankedByClause,
    RequirementClause,
    SurfaceScript,
    WhereClause,
    WithinClause,
)

_DURATION_RE = re.compile(
    r"^(?P<value>\d+(?:\.\d*)?|\.\d+)(?P<unit>s|min|h|d|w)$", re.IGNORECASE
)
_ANGLE_RE = re.compile(
    r"^(?P<value>\d+(?:\.\d*)?|\.\d+)(?P<unit>deg|arcmin|arcsec)?$",
    re.IGNORECASE,
)
_CLAUSE_PREFIXES = (
    "inside",
    "within ",
    "latest ",
    "where ",
    "filter ",
    "with ",
    "match",
    "order by ",
    "ranked by ",
)


class _DSLIndenter(Indenter):
    NL_type = "_NL"
    OPEN_PAREN_types: list[str] = []
    CLOSE_PAREN_types: list[str] = []
    INDENT_type = "_INDENT"
    DEDENT_type = "_DEDENT"
    tab_len = 8


def grammar_text() -> str:
    """Return the version-controlled formal grammar used by the parser."""

    return files("alertissimo.dsl").joinpath("grammar.lark").read_text(
        encoding="utf-8"
    )


@lru_cache(maxsize=1)
def _lark_parser() -> Lark:
    return Lark(
        grammar_text(),
        parser="lalr",
        lexer="contextual",
        postlex=_DSLIndenter(),
        propagate_positions=True,
    )


def _parse_duration(raw: str) -> Duration:
    match = _DURATION_RE.fullmatch(raw.strip())
    if match is None:
        raise ValueError("invalid duration")
    return Duration(
        value=float(match.group("value")),
        unit=match.group("unit").lower(),
    )


def _parse_angle(raw: str) -> AngularRadius:
    match = _ANGLE_RE.fullmatch(raw.strip())
    if match is None:
        raise ValueError("invalid angular radius")
    unit = match.group("unit")
    return AngularRadius(
        value=float(match.group("value")),
        unit=unit.lower() if unit else None,
    )


def _split_direction(
    raw: str,
) -> tuple[str, Literal["asc", "desc"] | None]:
    text = raw.strip()
    parts = text.rsplit(None, 1)
    if len(parts) == 2 and parts[1].lower() in {"asc", "desc"}:
        return text[: -len(parts[1])].rstrip(), parts[1].lower()  # type: ignore[return-value]
    return text, None


def _with_predicates(
    requirement: RequirementClause,
    predicates: tuple[str, ...],
) -> RequirementClause:
    """Rebuild a requirement so Pydantic validates newly attached predicates.

    ``model_copy(update=...)`` deliberately skips validation in Pydantic v2 and
    must not be used at this syntax boundary: scoped predicates need to pass the
    same production expression grammar as top-level WHERE/FILTER conditions.
    """

    return RequirementClause.model_validate(
        {
            **requirement.model_dump(),
            "predicates": predicates,
        }
    )


class _SurfaceTransformer(Transformer):
    """Transform formal syntax directly into the provider-independent surface AST."""

    def start(self, items):
        return items[0]

    def script(self, items):
        return SurfaceScript(candidates=items[0], clauses=tuple(items[1:]))

    def origin_list(self, items):
        return tuple(str(item).lower() for item in items)

    def via_clause(self, items):
        return "via", str(items[0]).lower()

    def from_clause(self, items):
        return "from", str(items[0]).lower()

    def using_clause(self, items):
        return "using", str(items[0])

    def candidate_statement(self, items):
        origins = items[0]
        broker = items[1][1] if len(items) > 1 else None
        return CandidateSet(origins=origins, broker=broker)

    def duration(self, items):
        return _parse_duration(str(items[0]))

    def inside_clause(self, items):
        return InsideClause(
            ra=float(items[0]),
            dec=float(items[1]),
            radius=_parse_angle(str(items[2])),
        )

    def within_relative(self, items):
        return WithinClause(duration=items[0], relative_to="now")

    def within_explicit(self, items):
        return WithinClause(
            start=str(items[0]).strip(),
            end=str(items[1]).strip(),
        )

    def latest_clause(self, items):
        return LatestClause(count=int(str(items[0])))

    def where_clause(self, items):
        return WhereClause(condition=str(items[0]).strip())

    def filter_clause(self, items):
        return FilterClause(condition=str(items[0]).strip())

    def requirement(self, items):
        product = str(items[0]).strip()
        qualifiers = {item[0]: item[1] for item in items[1:]}
        return RequirementClause(
            product=product,
            source=qualifiers.get("from"),
            via=qualifiers.get("via"),
            method=qualifiers.get("using"),
        )

    def scoped_bare(self, items):
        return str(items[0]).strip()

    def scoped_where(self, items):
        return str(items[0]).strip()

    def with_plain(self, items):
        return items[0]

    def with_colon(self, items):
        requirement = items[0]
        return _with_predicates(requirement, tuple(items[1:]))

    def with_where(self, items):
        requirement = items[0]
        return _with_predicates(requirement, (items[1],))

    def match_from(self, items):
        return "from", str(items[0]).lower()

    def match_within(self, items):
        return "within", items[0]

    def match_on(self, items):
        return "on", str(items[0]).strip()

    def match_clause(self, items):
        qualifiers = {item[0]: item[1] for item in items}
        return MatchClause(
            counterpart_origin=qualifiers.get("from"),
            via=qualifiers.get("via"),
            within=qualifiers.get("within"),
            on=qualifiers.get("on"),
        )

    def order_clause(self, items):
        expression, direction = _split_direction(str(items[0]))
        return OrderByClause(expression=expression, direction=direction)

    def ranked_clause(self, items):
        criterion, direction = _split_direction(str(items[0]))
        return RankedByClause(criterion=criterion, direction=direction)


_TRANSFORMER = _SurfaceTransformer()


def _indent_width(raw: str) -> int:
    prefix = raw[: len(raw) - len(raw.lstrip(" \t"))]
    return len(prefix.expandtabs(8))


def _canonicalize_layout(script: str) -> str:
    """Normalize cosmetic top-level indentation while retaining WITH scopes.

    Existing DSL examples freely indent top-level clauses for readability. The
    only indentation with semantic force in v0.1 is indentation relative to a
    preceding ``with`` line: after ``with ...:`` it introduces a conjunctive
    predicate block; after plain ``with ...`` it may introduce one scoped
    ``where`` line. Blank and comment-only lines preserve line count for
    diagnostics but never carry indentation state into Lark's indenter.
    """

    lines = script.splitlines()
    out: list[str] = []
    scope_mode: Literal["colon", "where"] | None = None
    scope_indent = -1

    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            out.append("")
            continue
        if raw.lstrip().startswith("#"):
            out.append(stripped)
            continue

        indent = _indent_width(raw)
        lowered = stripped.lower()

        if scope_mode == "colon" and indent > scope_indent:
            out.append("    " + stripped)
            continue
        if (
            scope_mode == "where"
            and indent > scope_indent
            and lowered.startswith("where ")
        ):
            out.append("    " + stripped)
            scope_mode = None
            continue

        scope_mode = None
        scope_indent = -1
        out.append(stripped)

        if lowered.startswith("with "):
            scope_indent = indent
            scope_mode = "colon" if stripped.endswith(":") else "where"

    return "\n".join(out) + ("\n" if script.endswith("\n") else "")


def _meaningful_top_level_lines(script: str) -> list[tuple[int, str]]:
    return [
        (number, raw.strip())
        for number, raw in enumerate(script.splitlines(), start=1)
        if raw.strip()
        and not raw.lstrip().startswith("#")
        and raw == raw.lstrip(" \t")
    ]


def _preflight_structure(script: str) -> None:
    lines = _meaningful_top_level_lines(script)
    if not lines:
        raise DSLParseError("DSL script is empty")

    first_line, first = lines[0]
    if not first.lower().startswith("objects from "):
        raise DSLParseError(
            "first statement must be 'objects from <origin>[, <origin> ...] "
            "[via <broker>]'",
            line=first_line,
        )

    filter_seen = False
    where_count = 0
    for line_no, text in lines[1:]:
        lowered = text.lower()
        if lowered.startswith("objects "):
            raise DSLParseError(
                "candidate origins are fixed by the first objects statement",
                line=line_no,
            )
        if not any(
            lowered == prefix.rstrip() or lowered.startswith(prefix)
            for prefix in _CLAUSE_PREFIXES
        ):
            raise DSLParseError(f"unknown DSL clause: {text!r}", line=line_no)
        if lowered.startswith("latest "):
            raw_count = text[len("latest ") :].strip()
            if not raw_count.isdigit() or int(raw_count) <= 0:
                raise DSLParseError(
                    "latest requires a positive integer count",
                    line=line_no,
                )
        if lowered.startswith("filter "):
            filter_seen = True
        elif lowered.startswith("where "):
            where_count += 1
            if where_count > 1:
                raise DSLParseError(
                    "only one general where clause is allowed",
                    line=line_no,
                )
            if filter_seen:
                raise DSLParseError(
                    "where belongs to the initial candidate pass; use filter for "
                    "later refinement",
                    line=line_no,
                )
        elif filter_seen and lowered.startswith(("inside", "within ", "latest ")):
            raise DSLParseError(
                "inside, within, and latest belong to the initial candidate pass",
                line=line_no,
            )


def parse_surface_script(script: str) -> SurfaceScript:
    """Parse declarative DSL text into a surface AST without orchestration lowering."""

    if not script or not script.strip():
        raise DSLParseError("DSL script is empty")
    normalized = _canonicalize_layout(script)
    _preflight_structure(normalized)

    try:
        result = _TRANSFORMER.transform(_lark_parser().parse(normalized))
    except VisitError as exc:
        if isinstance(exc.orig_exc, DSLParseError):
            raise exc.orig_exc from exc
        raise DSLParseError(str(exc.orig_exc)) from exc
    except UnexpectedInput as exc:
        raise DSLParseError(
            "syntax error",
            line=getattr(exc, "line", None),
            column=getattr(exc, "column", None),
        ) from exc
    except ValueError as exc:
        raise DSLParseError(str(exc)) from exc

    if not isinstance(result, SurfaceScript):
        raise DSLParseError("parser did not produce a surface script")
    return result


__all__ = ["grammar_text", "parse_surface_script"]
