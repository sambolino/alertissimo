"""Lark-backed parser for the formal Alertissimo DSL grammar."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
import re
from typing import Literal

from lark import Lark, Transformer, UnexpectedInput
from lark.exceptions import VisitError

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

    def with_clause(self, items):
        return items[0]

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


def _meaningful_lines(script: str) -> list[tuple[int, str]]:
    return [
        (number, raw.strip())
        for number, raw in enumerate(script.splitlines(), start=1)
        if raw.strip() and not raw.lstrip().startswith("#")
    ]


def _preflight_structure(lines: list[tuple[int, str]]) -> None:
    first_line, first = lines[0]
    if not first.lower().startswith("objects from "):
        raise DSLParseError(
            "first statement must be 'objects from <origin>[, <origin> ...] "
            "[via <broker>]'",
            line=first_line,
        )

    filter_seen = False
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
        elif lowered.startswith("where ") and filter_seen:
            raise DSLParseError(
                "where belongs to the initial candidate pass; use filter for "
                "later refinement",
                line=line_no,
            )


def parse_surface_script(script: str) -> SurfaceScript:
    """Parse declarative DSL text into a surface AST without orchestration lowering."""

    if not script or not script.strip():
        raise DSLParseError("DSL script is empty")
    lines = _meaningful_lines(script)
    if not lines:
        raise DSLParseError("DSL script is empty")
    _preflight_structure(lines)

    try:
        result = _TRANSFORMER.transform(_lark_parser().parse(script))
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
