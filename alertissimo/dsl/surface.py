"""User-facing declarative DSL surface models and parser.

This module intentionally stops before orchestration lowering. It preserves the
scientist's request as an ordered, provider-independent surface representation so
later compiler stages can perform ontology, capability, and IR validation without
forcing user vocabulary to mirror execution Step classes.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_NAME = r"[A-Za-z][A-Za-z0-9_.-]*"
_METHOD = r"[A-Za-z][A-Za-z0-9_.:-]*"
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
_DURATION_RE = re.compile(
    rf"^(?P<value>{_NUMBER})(?P<unit>s|min|h|d|w)$", re.IGNORECASE
)
_ANGLE_RE = re.compile(
    rf"^(?P<value>{_NUMBER})(?P<unit>deg|arcmin|arcsec)?$", re.IGNORECASE
)
_CANDIDATE_RE = re.compile(
    rf"^objects\s+from\s+(?P<origins>.+?)(?:\s+via\s+(?P<broker>{_NAME}))?$",
    re.IGNORECASE,
)
_INSIDE_RE = re.compile(
    rf"^inside\s*\(\s*(?P<ra>{_NUMBER})\s*,\s*(?P<dec>{_NUMBER})\s*,\s*"
    rf"(?P<radius>{_NUMBER}(?:deg|arcmin|arcsec)?)\s*\)$",
    re.IGNORECASE,
)
_REQUIREMENT_RE = re.compile(
    rf"^(?P<product>.+?)"
    rf"(?:\s+from\s+(?P<source>{_NAME}))?"
    rf"(?:\s+via\s+(?P<via>{_NAME}))?"
    rf"(?:\s+using\s+(?P<method>{_METHOD}))?$",
    re.IGNORECASE,
)


class SurfaceModel(BaseModel):
    """Strict immutable value object used only by the user-facing DSL surface."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DSLParseError(ValueError):
    """Surface-language syntax or structural error with an optional line number."""

    def __init__(self, message: str, *, line: int | None = None):
        self.message = message
        self.line = line
        prefix = f"Line {line}: " if line is not None else ""
        super().__init__(prefix + message)


class CandidateSet(SurfaceModel):
    """Initial object population. Candidate origins are fixed for the script."""

    kind: Literal["objects"] = "objects"
    origins: tuple[str, ...]
    broker: str | None = None

    @field_validator("origins")
    @classmethod
    def require_unique_origins(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("at least one candidate origin is required")
        if len(set(value)) != len(value):
            raise ValueError("candidate origins must be unique")
        return value


class AngularRadius(SurfaceModel):
    value: float = Field(gt=0)
    unit: Literal["deg", "arcmin", "arcsec"] | None = None


class InsideClause(SurfaceModel):
    kind: Literal["inside"] = "inside"
    ra: float = Field(ge=0, lt=360)
    dec: float = Field(ge=-90, le=90)
    radius: AngularRadius


class Duration(SurfaceModel):
    value: float = Field(gt=0)
    unit: Literal["s", "min", "h", "d", "w"]


class WithinClause(SurfaceModel):
    """Temporal window; one-value form is a lookback ending at runtime ``now``."""

    kind: Literal["within"] = "within"
    duration: Duration | None = None
    start: str | None = None
    end: str | None = None
    relative_to: Literal["now"] | None = None

    @model_validator(mode="after")
    def require_one_window_form(self) -> "WithinClause":
        relative = self.duration is not None
        explicit = self.start is not None or self.end is not None
        if relative == explicit:
            raise ValueError(
                "within must be either a duration or an explicit start/end window"
            )
        if relative and self.relative_to != "now":
            raise ValueError("single-value within is relative to now")
        if explicit and (self.start is None or self.end is None):
            raise ValueError("explicit within requires both start and end")
        if explicit and self.relative_to is not None:
            raise ValueError("explicit within cannot also be relative to now")
        return self


class LatestClause(SurfaceModel):
    kind: Literal["latest"] = "latest"
    count: int = Field(gt=0)


class WhereClause(SurfaceModel):
    kind: Literal["where"] = "where"
    condition: str

    @field_validator("condition")
    @classmethod
    def require_condition(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("where requires a condition")
        return value


class FilterClause(SurfaceModel):
    kind: Literal["filter"] = "filter"
    condition: str

    @field_validator("condition")
    @classmethod
    def require_condition(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("filter requires a condition")
        return value


class RequirementClause(SurfaceModel):
    """Semantic enrichment requirement; it does not filter the candidate set."""

    kind: Literal["with"] = "with"
    product: str
    source: str | None = None
    via: str | None = None
    method: str | None = None

    @field_validator("product")
    @classmethod
    def require_product(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("with requires a semantic product")
        return value


class MatchClause(SurfaceModel):
    """Association request; counterpart origin never changes candidate origins."""

    kind: Literal["match"] = "match"
    counterpart_origin: str | None = None
    via: str | None = None
    within: Duration | None = None
    on: str | None = None

    @model_validator(mode="after")
    def require_counterpart_or_predicate(self) -> "MatchClause":
        if self.counterpart_origin is None and self.on is None:
            raise ValueError("match requires a counterpart origin or an 'on' predicate")
        return self


class OrderByClause(SurfaceModel):
    kind: Literal["order_by"] = "order_by"
    expression: str
    direction: Literal["asc", "desc"] | None = None

    @field_validator("expression")
    @classmethod
    def require_expression(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("order by requires an expression")
        return value


class RankedByClause(SurfaceModel):
    kind: Literal["ranked_by"] = "ranked_by"
    criterion: str
    direction: Literal["asc", "desc"] | None = None

    @field_validator("criterion")
    @classmethod
    def require_criterion(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("ranked by requires a criterion")
        return value


SurfaceClause = Annotated[
    InsideClause
    | WithinClause
    | LatestClause
    | WhereClause
    | FilterClause
    | RequirementClause
    | MatchClause
    | OrderByClause
    | RankedByClause,
    Field(discriminator="kind"),
]


class SurfaceScript(SurfaceModel):
    """Ordered user intent before lowering to orchestration IR."""

    candidates: CandidateSet
    clauses: tuple[SurfaceClause, ...] = ()


def _parse_names(raw: str, *, line: int) -> tuple[str, ...]:
    names = tuple(part.strip().lower() for part in raw.split(",") if part.strip())
    if not names:
        raise DSLParseError("objects from requires at least one origin", line=line)
    invalid = [name for name in names if re.fullmatch(_NAME, name) is None]
    if invalid:
        raise DSLParseError(f"invalid origin name: {invalid[0]!r}", line=line)
    if len(set(names)) != len(names):
        raise DSLParseError("candidate origins must be unique", line=line)
    return names


def _parse_duration(raw: str, *, line: int) -> Duration:
    match = _DURATION_RE.fullmatch(raw.strip())
    if match is None:
        raise DSLParseError(
            "duration must use one of s, min, h, d, w (for example 72h or 7d)",
            line=line,
        )
    return Duration(value=float(match.group("value")), unit=match.group("unit").lower())


def _parse_radius(raw: str, *, line: int) -> AngularRadius:
    match = _ANGLE_RE.fullmatch(raw.strip())
    if match is None:
        raise DSLParseError(
            "angular radius must be numeric with optional deg, arcmin, or arcsec unit",
            line=line,
        )
    unit = match.group("unit")
    return AngularRadius(
        value=float(match.group("value")), unit=unit.lower() if unit else None
    )


def _parse_requirement(raw: str, *, line: int) -> RequirementClause:
    match = _REQUIREMENT_RE.fullmatch(raw.strip())
    if match is None:
        raise DSLParseError(
            "invalid with clause; expected 'with <product> [from <source>] "
            "[via <broker>] [using <method>]'",
            line=line,
        )
    return RequirementClause(
        product=match.group("product").strip(),
        source=match.group("source").lower() if match.group("source") else None,
        via=match.group("via").lower() if match.group("via") else None,
        method=match.group("method") if match.group("method") else None,
    )


def _consume_name(text: str, keyword: str, *, line: int) -> tuple[str, str]:
    prefix = keyword + " "
    if not text.lower().startswith(prefix):
        raise DSLParseError(f"expected {keyword}", line=line)
    remainder = text[len(prefix):].lstrip()
    match = re.match(rf"(?P<name>{_NAME})(?:\s+|$)", remainder)
    if match is None:
        raise DSLParseError(f"{keyword} requires a name", line=line)
    name = match.group("name").lower()
    return name, remainder[match.end():].lstrip()


def _parse_match(raw: str, *, line: int) -> MatchClause:
    text = raw.strip()
    counterpart: str | None = None
    via: str | None = None
    window: Duration | None = None
    predicate: str | None = None

    if text.lower().startswith("from "):
        counterpart, text = _consume_name(text, "from", line=line)
    if text.lower().startswith("via "):
        via, text = _consume_name(text, "via", line=line)
    if text.lower().startswith("within "):
        remainder = text[len("within "):].lstrip()
        token, _, tail = remainder.partition(" ")
        window = _parse_duration(token, line=line)
        text = tail.lstrip()
    if text.lower().startswith("on "):
        predicate = text[len("on "):].strip()
        text = ""
    if text:
        raise DSLParseError(
            "invalid match clause; expected 'match [from <origin>] [via <broker>] "
            "[within <duration>] [on <predicate>]'",
            line=line,
        )
    try:
        return MatchClause(
            counterpart_origin=counterpart,
            via=via,
            within=window,
            on=predicate,
        )
    except ValueError as exc:
        raise DSLParseError(str(exc), line=line) from exc


def _parse_sort(
    raw: str, *, ranked: bool, line: int
) -> OrderByClause | RankedByClause:
    text = raw.strip()
    direction: Literal["asc", "desc"] | None = None
    match = re.match(
        r"^(?P<body>.+?)(?:\s+(?P<direction>asc|desc))?$", text, re.IGNORECASE
    )
    if match is None or not match.group("body").strip():
        raise DSLParseError("sorting clause requires a target", line=line)
    body = match.group("body").strip()
    if match.group("direction"):
        direction = match.group("direction").lower()  # type: ignore[assignment]
    if ranked:
        return RankedByClause(criterion=body, direction=direction)
    return OrderByClause(expression=body, direction=direction)


def parse_surface_script(script: str) -> SurfaceScript:
    """Parse the first production DSL surface without lowering to WorkflowIR.

    Indentation is intentionally cosmetic in this first slice. Clause order is
    preserved exactly; later compiler stages decide which clauses can be pushed
    into provider search and which require local working-context operations.
    """

    if not script or not script.strip():
        raise DSLParseError("DSL script is empty")

    lines: list[tuple[int, str]] = []
    for number, raw in enumerate(script.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append((number, stripped))

    if not lines:
        raise DSLParseError("DSL script is empty")

    first_line, first = lines[0]
    candidate_match = _CANDIDATE_RE.fullmatch(first)
    if candidate_match is None:
        raise DSLParseError(
            "first statement must be 'objects from <origin>[, <origin> ...] "
            "[via <broker>]'",
            line=first_line,
        )
    candidates = CandidateSet(
        origins=_parse_names(candidate_match.group("origins"), line=first_line),
        broker=(candidate_match.group("broker") or "").lower() or None,
    )

    clauses: list[SurfaceClause] = []
    filter_seen = False
    for line_no, text in lines[1:]:
        lowered = text.lower()
        try:
            if lowered.startswith("objects "):
                raise DSLParseError(
                    "candidate origins are fixed by the first objects statement",
                    line=line_no,
                )
            if lowered.startswith("inside"):
                match = _INSIDE_RE.fullmatch(text)
                if match is None:
                    raise DSLParseError(
                        "inside must use '(ra, dec, radius)'",
                        line=line_no,
                    )
                clauses.append(
                    InsideClause(
                        ra=float(match.group("ra")),
                        dec=float(match.group("dec")),
                        radius=_parse_radius(match.group("radius"), line=line_no),
                    )
                )
                continue
            if lowered.startswith("within "):
                body = text[len("within "):].strip()
                if "," in body:
                    parts = [part.strip() for part in body.split(",")]
                    if len(parts) != 2 or not all(parts):
                        raise DSLParseError(
                            "explicit within requires exactly two comma-separated bounds",
                            line=line_no,
                        )
                    clauses.append(WithinClause(start=parts[0], end=parts[1]))
                else:
                    clauses.append(
                        WithinClause(
                            duration=_parse_duration(body, line=line_no),
                            relative_to="now",
                        )
                    )
                continue
            if lowered.startswith("latest "):
                raw_count = text[len("latest "):].strip()
                if not raw_count.isdigit() or int(raw_count) <= 0:
                    raise DSLParseError(
                        "latest requires a positive integer count", line=line_no
                    )
                clauses.append(LatestClause(count=int(raw_count)))
                continue
            if lowered.startswith("where "):
                if filter_seen:
                    raise DSLParseError(
                        "where belongs to the initial candidate pass; use filter for "
                        "later refinement",
                        line=line_no,
                    )
                clauses.append(WhereClause(condition=text[len("where "):]))
                continue
            if lowered.startswith("filter "):
                filter_seen = True
                clauses.append(FilterClause(condition=text[len("filter "):]))
                continue
            if lowered.startswith("with "):
                clauses.append(
                    _parse_requirement(text[len("with "):], line=line_no)
                )
                continue
            if lowered == "match" or lowered.startswith("match "):
                clauses.append(_parse_match(text[len("match"):], line=line_no))
                continue
            if lowered.startswith("order by "):
                clauses.append(
                    _parse_sort(
                        text[len("order by "):], ranked=False, line=line_no
                    )
                )
                continue
            if lowered.startswith("ranked by "):
                clauses.append(
                    _parse_sort(
                        text[len("ranked by "):], ranked=True, line=line_no
                    )
                )
                continue
            raise DSLParseError(f"unknown DSL clause: {text!r}", line=line_no)
        except DSLParseError:
            raise
        except ValueError as exc:
            raise DSLParseError(str(exc), line=line_no) from exc

    return SurfaceScript(candidates=candidates, clauses=tuple(clauses))


__all__ = [
    "AngularRadius",
    "CandidateSet",
    "DSLParseError",
    "Duration",
    "FilterClause",
    "InsideClause",
    "LatestClause",
    "MatchClause",
    "OrderByClause",
    "RankedByClause",
    "RequirementClause",
    "SurfaceClause",
    "SurfaceScript",
    "WhereClause",
    "WithinClause",
    "parse_surface_script",
]
