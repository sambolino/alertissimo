"""Provider-independent semantic predicates used by orchestration IR.

These models are the canonical middle-layer representation of filtering intent.
They refer only to ontology record families/fields plus semantic qualifiers; they
never name provider endpoints or physical request parameters.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias
from functools import lru_cache
import math
import re

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator


NonEmptyStr = Annotated[str, Field(min_length=1, pattern=r".*\S.*")]


class PredicateModel(BaseModel):
    """Strict immutable base for semantic predicate nodes."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SemanticReference(PredicateModel):
    """One ontology reference, optionally qualified by producer/channel.

    ``semantic_type`` is the ontology record family (for example
    ``classification``). ``field_path`` is relative to that record. Empty
    ``field_path`` is allowed only for existence tests over the record family.
    """

    kind: Literal["reference"] = "reference"
    semantic_type: NonEmptyStr
    field_path: str = ""
    producer: NonEmptyStr | None = None
    channel: NonEmptyStr | None = None

    @field_validator("field_path")
    @classmethod
    def normalize_field_path(cls, value: str) -> str:
        value = value.strip().strip(".")
        if "@" in value:
            raise ValueError("field_path must be relative to its semantic record")
        return value

    @property
    def ontology_path(self) -> str:
        return self.semantic_type + (f".{self.field_path}" if self.field_path else "")

    @property
    def qualified_record_type(self) -> str:
        value = self.semantic_type
        if self.producer is not None:
            value += f"@{self.producer}"
            if self.channel is not None:
                value += f":{self.channel}"
        elif self.channel is not None:
            value += f"@*:{self.channel}"
        return value


class PredicateLiteral(PredicateModel):
    kind: Literal["literal"] = "literal"
    value: str | int | float | bool | tuple[StrictInt, ...]

    @field_validator("value")
    @classmethod
    def canonical_code_set(cls, value):
        if isinstance(value, tuple) and (not value or value != tuple(sorted(set(value)))):
            raise ValueError("code tuples must be non-empty, sorted and duplicate-free")
        return value


class ElementReference(PredicateModel):
    """A path relative to the innermost count condition's element."""

    kind: Literal["element_reference"] = "element_reference"
    field_path: NonEmptyStr

    @field_validator("field_path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        if "@" in value or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_{}-]*(?:\.[A-Za-z0-9_{}-]+)*", value):
            raise ValueError("element reference must be an unqualified relative path")
        return value


class AggregateOperand(PredicateModel):
    kind: Literal["aggregate"] = "aggregate"
    function: Literal["count", "min", "max"]
    reference: SemanticReference
    condition: "Predicate | None" = None

    @model_validator(mode="after")
    def count_condition_only(self):
        if self.condition is not None and self.function != "count":
            raise ValueError("only count accepts an element condition")
        model = _collection_paths()
        path = self.reference.ontology_path
        boundaries = model.array_boundaries(path)
        if self.reference.semantic_type not in model.concrete_record_types:
            raise ValueError("aggregate must name a concrete record collection")
        if self.function == "count":
            if self.reference.field_path and (not boundaries or boundaries[-1] != path):
                raise ValueError("count reference must resolve to an array or record collection")
        elif not boundaries or boundaries[-1] == path or not model.is_scalar_path(path):
            raise ValueError("min/max reference must resolve to a scalar field inside an array element")
        return self


PredicateOperand: TypeAlias = Annotated[
    SemanticReference | ElementReference | PredicateLiteral | AggregateOperand,
    Field(discriminator="kind"),
]


class ComparisonPredicate(PredicateModel):
    kind: Literal["comparison"] = "comparison"
    operator: Literal["=", "!=", "<", "<=", ">", ">="]
    left: PredicateOperand
    right: PredicateOperand

    @model_validator(mode="after")
    def aggregate_numeric_comparison(self):
        for aggregate, other in ((self.left, self.right), (self.right, self.left)):
            if isinstance(aggregate, AggregateOperand) and not (
                isinstance(other, PredicateLiteral)
                and (type(other.value) is int or type(other.value) is float and math.isfinite(other.value))
            ):
                raise ValueError("an aggregate must be compared with a finite numeric literal")
        return self

    @model_validator(mode="after")
    def restrict_code_sets(self):
        for literal, reference in ((self.left, self.right), (self.right, self.left)):
            is_taxon = (isinstance(reference, SemanticReference)
                        and reference.semantic_type == "classification"
                        and reference.field_path == "best.taxon")
            if isinstance(literal, PredicateLiteral):
                if isinstance(literal.value, tuple) and not (is_taxon and self.operator in {"=", "!="}):
                    raise ValueError("code tuples are only legal for classification.best.taxon = or !=")
                if is_taxon and (self.operator not in {"=", "!="} or not isinstance(literal.value, tuple)):
                    raise ValueError("classification.best.taxon requires = or != and resolved code tuples")
            elif is_taxon:
                raise ValueError("classification.best.taxon requires a resolved literal")
        return self


class ExistsPredicate(PredicateModel):
    kind: Literal["exists"] = "exists"
    reference: SemanticReference | ElementReference


class NotPredicate(PredicateModel):
    kind: Literal["not"] = "not"
    operand: "Predicate"


class BooleanPredicate(PredicateModel):
    kind: Literal["boolean"] = "boolean"
    operator: Literal["and", "or"]
    operands: tuple["Predicate", ...]

    @model_validator(mode="after")
    def require_multiple_operands(self) -> "BooleanPredicate":
        if len(self.operands) < 2:
            raise ValueError("boolean predicate requires at least two operands")
        return self


class QuantifierPredicate(PredicateModel):
    kind: Literal["quantifier"] = "quantifier"
    quantifier: Literal["any", "every"]
    parameter: Literal["filter", "output"]
    values: tuple[NonEmptyStr, ...] | None = None
    operand: "Predicate"

    @model_validator(mode="after")
    def explicit_domain(self):
        if self.values is not None and (not self.values or len(set(self.values)) != len(self.values)):
            raise ValueError("quantifier values must be nonempty and duplicate-free")
        return self


Predicate: TypeAlias = Annotated[
    ComparisonPredicate | BooleanPredicate | NotPredicate | ExistsPredicate | QuantifierPredicate,
    Field(discriminator="kind"),
]

AggregateOperand.model_rebuild()
ComparisonPredicate.model_rebuild()
NotPredicate.model_rebuild()
BooleanPredicate.model_rebuild()
QuantifierPredicate.model_rebuild()


def _positive_references(predicate: Predicate | None) -> tuple[SemanticReference, ...]:
    if predicate is None:
        return ()
    if isinstance(predicate, ComparisonPredicate):
        return tuple(
            operand
            for operand in (predicate.left, predicate.right)
            if isinstance(operand, SemanticReference)
        )
    if isinstance(predicate, ExistsPredicate):
        return (predicate.reference,) if isinstance(predicate.reference, SemanticReference) else ()
    if isinstance(predicate, BooleanPredicate) and predicate.operator == "and":
        return tuple(
            reference
            for operand in predicate.operands
            for reference in _positive_references(operand)
        )
    if isinstance(predicate, NotPredicate):
        return ()
    return ()


def predicate_requires_reference(
    predicate: Predicate | None, requirement: SemanticReference
) -> bool:
    """Require a qualified reference positively, including conjunctions only."""
    for reference in _positive_references(predicate):
        if reference.semantic_type != requirement.semantic_type:
            continue
        if requirement.producer is not None and reference.producer != requirement.producer:
            continue
        if requirement.channel is not None and reference.channel != requirement.channel:
            continue
        return True
    return False


def and_predicates(predicates: list[Predicate] | tuple[Predicate, ...]) -> Predicate | None:
    """Conjoin predicates without manufacturing a one-child boolean node."""

    items = tuple(predicate for predicate in predicates if predicate is not None)
    if not items:
        return None
    if len(items) == 1:
        return items[0]
    return BooleanPredicate(operator="and", operands=items)


def iter_semantic_references(predicate: Predicate, _collection: SemanticReference | None = None):
    """Yield absolute material dependencies, including element-relative leaves."""
    def reference(value):
        if isinstance(value, SemanticReference):
            yield value
        elif isinstance(value, ElementReference) and _collection is not None:
            path = ".".join(p for p in (_collection.field_path, value.field_path) if p)
            yield _collection.model_copy(update={"field_path": path})
        elif isinstance(value, AggregateOperand):
            yield value.reference
            if value.condition is not None:
                yield from iter_semantic_references(value.condition, value.reference)

    if isinstance(predicate, ComparisonPredicate):
        yield from reference(predicate.left)
        yield from reference(predicate.right)
    elif isinstance(predicate, ExistsPredicate):
        yield from reference(predicate.reference)
    elif isinstance(predicate, (NotPredicate, QuantifierPredicate)):
        yield from iter_semantic_references(predicate.operand, _collection)
    elif isinstance(predicate, BooleanPredicate):
        for operand in predicate.operands:
            yield from iter_semantic_references(operand, _collection)


def contains_collection_predicate(predicate) -> bool:
    if isinstance(predicate, (AggregateOperand, QuantifierPredicate, ElementReference)):
        return True
    if isinstance(predicate, ComparisonPredicate):
        return any(contains_collection_predicate(value) for value in (predicate.left, predicate.right))
    if isinstance(predicate, ExistsPredicate):
        return contains_collection_predicate(predicate.reference)
    if isinstance(predicate, NotPredicate):
        return contains_collection_predicate(predicate.operand)
    if isinstance(predicate, BooleanPredicate):
        return any(contains_collection_predicate(item) for item in predicate.operands)
    return False


def iter_aggregate_operands(predicate):
    if isinstance(predicate, AggregateOperand):
        yield predicate
        if predicate.condition is not None:
            yield from iter_aggregate_operands(predicate.condition)
    elif isinstance(predicate, ComparisonPredicate):
        yield from iter_aggregate_operands(predicate.left)
        yield from iter_aggregate_operands(predicate.right)
    elif isinstance(predicate, (NotPredicate, QuantifierPredicate)):
        yield from iter_aggregate_operands(predicate.operand)
    elif isinstance(predicate, BooleanPredicate):
        for child in predicate.operands:
            yield from iter_aggregate_operands(child)


def contains_container_reference(predicate) -> bool:
    return any(reference.field_path and not _collection_paths().is_scalar_path(reference.ontology_path)
               for reference in iter_semantic_references(predicate))


def validate_collection_selectors(predicate, material):
    """Reject known product ambiguity; material entries are noun/producer/channel/origin."""
    for aggregate in iter_aggregate_operands(predicate):
        ref = aggregate.reference
        if not ref.field_path:
            continue  # A record collection counts records, not pooled product arrays.
        matches = {}
        for noun, producer, channel, origin in material:
            if (noun != ref.semantic_type or ref.producer is not None and ref.producer != producer
                or ref.channel is not None and ref.channel != channel):
                continue
            matches.setdefault(origin, set()).add((producer, channel))
        if any(len(products) > 1 for products in matches.values()):
            raise ValueError("ambiguous collection product; qualify the selector, e.g. lightcurve@ztf:fink.points")


@lru_cache(maxsize=1)
def _collection_paths():
    from alertissimo.data_layer.semantic_model import SemanticPathModel
    return SemanticPathModel.from_ontology()


def validate_collection_predicate(predicate, *, semantic_paths=None, origins=()):
    """Validate contextual collection invariants at DSL and canonical IR boundaries."""
    if not contains_collection_predicate(predicate):
        return
    model = semantic_paths or _collection_paths()
    required = ("parameter_scopes", "array_boundaries", "parameter_domain", "parameter_origins",
                "is_scalar_path", "is_valid_element_path", "concrete_record_types")
    if not all(hasattr(model, name) for name in required):
        raise ValueError("collection predicates require ontology array, scalar and parameter metadata")

    def path(reference):
        return reference.semantic_type + ("." + reference.field_path if reference.field_path else "")

    def parameters(value, bound):
        names = set(re.findall(r"\{([^{}]+)\}", value))
        if names - bound:
            raise ValueError(f"unbound ontology parameter(s): {', '.join(sorted(names - bound))}")
        declared = {name for _, name in model.parameter_scopes(value)}
        if names - declared:
            raise ValueError("parameter must occupy its declared ontology path scope")

    def visit(node, bound=frozenset(), collection=None):
        if isinstance(node, QuantifierPredicate):
            if node.parameter in bound:
                raise ValueError(f"quantifier parameter {node.parameter!r} shadows an enclosing quantifier")
            refs = tuple(iter_semantic_references(node.operand, collection))
            relevant = tuple(ref for ref in refs if "{" + node.parameter + "}" in ref.field_path)
            if node.parameter == "output" and not relevant:
                raise ValueError("output domain requires a bound classification assessment path")
            if node.parameter == "filter" and any(
                model.parameter_domain("photometry.{filter}", origin) is None for origin in origins
            ):
                raise ValueError("candidate origin has no declared filter domain")
            for ref in relevant:
                scopes = {name for _, name in model.parameter_scopes(path(ref))}
                if node.parameter not in scopes:
                    raise ValueError("quantifier parameter has no matching ontology path scope")
            if node.parameter == "output":
                selectors = {(r.semantic_type, r.producer, r.channel) for r in relevant}
                if len(selectors) != 1 or any(r.semantic_type != "classification" for r in relevant):
                    raise ValueError("output domain must bind one classification selector")
                if node.quantifier == "every" and any(r.producer is None for r in relevant):
                    raise ValueError("for every {output} requires a single producer-qualified classification selector")
            if node.values is not None:
                # Explicit restrictions require a finite authored domain. Runtime
                # classification outputs do not supply a static declared domain.
                domain_path = "photometry.{filter}" if node.parameter == "filter" else "classification.assessment.{output}"
                domain_origins = tuple(origins) or model.parameter_origins(domain_path)
                domains = [model.parameter_domain(domain_path, origin) for origin in domain_origins]
                if not domains or any(domain is None for domain in domains):
                    raise ValueError(f"explicit {node.parameter} restriction requires a declared finite domain")
                if not origins:
                    domains = [set().union(*domains)]
                if any(set(node.values) - set(domain) for domain in domains):
                    raise ValueError("quantifier values must be members of the candidate origin's declared domain")
            visit(node.operand, bound | {node.parameter}, collection)
        elif isinstance(node, AggregateOperand):
            reference_path = path(node.reference)
            parameters(reference_path, bound)
            if node.reference.semantic_type not in model.concrete_record_types:
                raise ValueError("aggregate must name a concrete record collection")
            boundaries = model.array_boundaries(reference_path)
            if node.function == "count":
                if node.reference.field_path and (not boundaries or boundaries[-1] != reference_path):
                    raise ValueError("count reference must resolve to an array or record collection")
            elif not boundaries or boundaries[-1] == reference_path or not model.is_scalar_path(reference_path):
                raise ValueError("min/max reference must resolve to a scalar field inside an array element")
            if node.condition is not None:
                visit(node.condition, bound, node.reference)
        elif isinstance(node, ElementReference):
            if collection is None:
                raise ValueError("element reference is only valid inside a count condition")
            absolute = ".".join(p for p in (path(collection), node.field_path) if p)
            parameters(absolute, bound)
            valid = (model.is_valid_element_path(path(collection), node.field_path)
                     if collection.field_path else model.is_valid(f"{collection.semantic_type}@dsl.{node.field_path}"))
            if not valid or node.field_path.split(".", 1)[0] in model.record_types:
                raise ValueError("count conditions require paths relative to the current element")
        elif isinstance(node, SemanticReference):
            if collection is not None:
                raise ValueError("count conditions require element-relative references")
            parameters(path(node), bound)
        elif isinstance(node, ComparisonPredicate):
            visit(node.left, bound, collection)
            visit(node.right, bound, collection)
        elif isinstance(node, ExistsPredicate):
            visit(node.reference, bound, collection)
        elif isinstance(node, NotPredicate):
            visit(node.operand, bound, collection)
        elif isinstance(node, BooleanPredicate):
            for child in node.operands:
                visit(child, bound, collection)

    visit(predicate)


__all__ = [
    "AggregateOperand", "ElementReference", "QuantifierPredicate",
    "contains_collection_predicate", "contains_container_reference", "validate_collection_predicate",
    "iter_aggregate_operands", "validate_collection_selectors",
    "BooleanPredicate",
    "ComparisonPredicate",
    "ExistsPredicate",
    "NotPredicate",
    "Predicate",
    "PredicateLiteral",
    "PredicateModel",
    "PredicateOperand",
    "SemanticReference",
    "and_predicates",
    "iter_semantic_references",
    "predicate_requires_reference",
]
