"""Evaluate semantic predicates against normalized Portfolio data.

This is the second filtering realization: predicates not safely expressible as
provider input constraints are evaluated after normalization and prune candidate
Portfolios without changing the semantic condition itself.
"""

from __future__ import annotations

from collections.abc import Mapping
import math
import operator
import re
from typing import Any

from alertissimo.data_layer.representations import Portfolio, SemanticRecord
from alertissimo.data_layer.runtime.classification_headline import (
    compare_taxa, headline_reference, is_headline_record, materialize_headlines,
)
from alertissimo.orchestration.ir.predicates import (
    AggregateOperand, ElementReference, QuantifierPredicate, _collection_paths,
    BooleanPredicate,
    ComparisonPredicate,
    ExistsPredicate,
    NotPredicate,
    Predicate,
    PredicateLiteral,
    SemanticReference,
    iter_semantic_references,
)


_COMPARATORS = {
    "=": operator.eq,
    "!=": operator.ne,
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}
_MISSING = object()


def _record_parts(semantic_type: str) -> tuple[str, str | None, str | None]:
    noun, at, qualifiers = semantic_type.partition("@")
    if not at:
        return noun, None, None
    producer, colon, channel = qualifiers.partition(":")
    return noun, producer or None, (channel or None) if colon else None


def _selector(reference: SemanticReference) -> tuple[str, str | None, str | None]:
    return reference.semantic_type, reference.producer, reference.channel


def _record_matches(record: SemanticRecord, reference: SemanticReference, portfolio: Portfolio) -> bool:
    noun, producer, channel = _record_parts(record.semantic_type)
    if noun != reference.semantic_type:
        return False
    if reference.producer is not None and producer != reference.producer:
        return False
    if channel is None and reference.channel is not None and record.internal_source is not None:
        # Legacy fixed-producer records (for example classification@fink) omit
        # the channel suffix. Only their own execution provenance can supply it;
        # another broker present in the Portfolio is not evidence for this record.
        execution = portfolio.execution(record.internal_source.internal_execution_id)
        channel = execution.broker if execution is not None else None
    if reference.channel is not None and channel != reference.channel:
        return False
    return True


def _record_value(record: SemanticRecord, reference: SemanticReference, portfolio: Portfolio) -> Any:
    if not _record_matches(record, reference, portfolio):
        return _MISSING
    if not reference.field_path:
        return True
    if reference.field_path == "best.taxon" and reference.semantic_type == "classification" and (
        record.get("best.status") != "available" or record.get("best.scope") != "candidate"
    ):
        return _MISSING
    return record.get(reference.field_path, _MISSING)


def _available(value: Any) -> bool:
    return value is not _MISSING and value is not None and not (
        isinstance(value, float) and not math.isfinite(value)
    )


def _existing_component(record, reference, portfolio, *, value=_MISSING):
    if value is _MISSING:
        value = _record_value(record, reference, portfolio)
    if reference.field_path and not _collection_paths().is_scalar_path(reference.ontology_path):
        if value is _MISSING:
            value = _lookup(record, reference.field_path)
        if value is _MISSING:
            values = (v for key, v in record.fields.items() if key.startswith(reference.field_path + "."))
            return any(_available(v) and (bool(v) if isinstance(v, (Mapping, tuple, list)) else True) for v in values)
        return _available(value) and (bool(value) if isinstance(value, (Mapping, tuple, list)) else True)
    return _available(value)


def _compare(left: Any, operator_name: str, right: Any) -> bool | None:
    """None is unavailable evidence, and must remain unavailable under NOT."""
    if not _available(left) or not _available(right):
        return None
    numeric = (int, float)
    if isinstance(left, bool) or isinstance(right, bool):
        compatible = isinstance(left, bool) and isinstance(right, bool)
    else:
        compatible = (
            isinstance(left, numeric) and isinstance(right, numeric)
            or isinstance(left, str) and isinstance(right, str)
        )
    if not compatible:
        return None
    try:
        return bool(_COMPARATORS[operator_name](left, right))
    except (TypeError, ValueError):
        return None


def _matching_records(
    portfolio: Portfolio,
    selector: tuple[str, str | None, str | None],
) -> tuple[SemanticRecord, ...]:
    probe = SemanticReference(
        semantic_type=selector[0],
        producer=selector[1],
        channel=selector[2],
    )
    return tuple(record for record in portfolio.records if _record_matches(record, probe, portfolio))


def _lookup(value: Any, path: str) -> Any:
    """Read normalized flat fields and nested collection-element dictionaries."""
    if isinstance(value, SemanticRecord):
        value = value.fields
    parts = path.split(".") if path else ()
    for index, component in enumerate(parts):
        if not isinstance(value, Mapping):
            return _MISSING
        remainder = ".".join(parts[index:])
        if remainder in value:
            return value[remainder]
        value = value.get(component, _MISSING)
    return value


def _branch_present(value: Any, path: str) -> bool:
    if isinstance(value, SemanticRecord):
        value = value.fields
    if not isinstance(value, Mapping):
        return False
    if any(key == path or key.startswith(path + ".") for key in value):
        return True
    first, dot, rest = path.partition(".")
    return bool(dot and _branch_present(value.get(first, _MISSING), rest))


def _array_members(value: Any, path: str) -> tuple[tuple[Any, ...] | None, bool]:
    """Resolve an explicit array path within one product, retaining malformed gaps."""
    if isinstance(value, SemanticRecord):
        value = value.fields
    if not path:
        return (tuple(value), True) if isinstance(value, (tuple, list)) else (None, False)
    if isinstance(value, (tuple, list)):
        members, valid, found = [], True, not value
        for item in value:
            current, shape = _array_members(item, path)
            valid = valid and shape
            if current is not None:
                found = True
                members.extend(current)
        return (tuple(members) if found else None), valid
    if not isinstance(value, Mapping):
        return None, False
    if path in value:
        return _array_members(value[path], "")
    first, dot, rest = path.partition(".")
    if first not in value:
        return None, False
    return _array_members(value[first], rest if dot else "")


def _compare_interval(
    interval: tuple[int | float, int | float] | None,
    operator_name: str, value: int | float, *, integer: bool = False,
) -> bool | None:
    if interval is None:
        return None
    lower, upper = interval
    if operator_name in {"=", "!="}:
        equal = (False if value < lower or value > upper
                 or integer and type(value) is float and not value.is_integer()
                 else True if lower == upper == value else None)
        return equal if operator_name == "=" or equal is None else not equal
    if operator_name == "<":
        return True if upper < value else False if lower >= value else None
    if operator_name == "<=":
        return True if upper <= value else False if lower > value else None
    if operator_name == ">":
        return True if lower > value else False if upper <= value else None
    if operator_name == ">=":
        return True if lower >= value else False if upper < value else None
    raise ValueError(f"unknown comparison operator {operator_name!r}")


def _scalar_references(node):
    # Aggregates bind whole products/record collections independently of scalar
    # witness search; their references must never become a first-match choice.
    if isinstance(node, ComparisonPredicate):
        for operand in (node.left, node.right):
            if isinstance(operand, SemanticReference):
                yield operand
    elif isinstance(node, ExistsPredicate) and isinstance(node.reference, SemanticReference):
        yield node.reference
    elif isinstance(node, (NotPredicate, QuantifierPredicate)):
        yield from _scalar_references(node.operand)
    elif isinstance(node, BooleanPredicate):
        for operand in node.operands:
            yield from _scalar_references(operand)


def _element_paths(node, filter_domain=None):
    """Collect this element's branch dependencies, respecting inner quantifiers.

    Expand an inner filter domain for membership before evaluating its condition;
    otherwise NOT inside an inner quantifier could admit another band's point.
    Nested aggregates bind their own elements and deliberately contribute no path.
    """
    if isinstance(node, ComparisonPredicate):
        for operand in (node.left, node.right):
            if isinstance(operand, ElementReference):
                yield operand.field_path
    elif isinstance(node, ExistsPredicate) and isinstance(node.reference, ElementReference):
        yield node.reference.field_path
    elif isinstance(node, QuantifierPredicate) and node.parameter == "filter":
        for path in _element_paths(node.operand, filter_domain):
            domain = node.values or filter_domain
            if domain:
                for value in domain:
                    yield path.replace("{filter}", value)
            else:
                yield path  # Unresolved domain must remain unavailable.
    elif isinstance(node, (NotPredicate, QuantifierPredicate)):
        yield from _element_paths(node.operand, filter_domain)
    elif isinstance(node, BooleanPredicate):
        for operand in node.operands:
            yield from _element_paths(operand, filter_domain)


def evaluate_portfolio_predicate_truth(
    portfolio: Portfolio, predicate: Predicate, *, diagnostics: list[str] | None = None,
    collection_evidence: Mapping[tuple[str, ...], tuple[bool, frozenset[str]]] | None = None,
) -> bool | None:
    """Evaluate one predicate in the existing scalar witness search using Kleene logic.

    ``collection_evidence`` is transient explicit evidence keyed by record ID and
    exact array path, with (complete, delivered bands) values. A successful required
    component may also supply (Portfolio ID, qualified array) for an empty receipt.
    A third key member, "detections", restricts a proof to count conditions that
    entail upper_limit = false. Record collections always retain open completeness.
    Diagnostics use the caller's existing warnings collector, including when a
    candidate is rejected. No Portfolio or runtime schema field is introduced.
    """
    selectors = tuple(dict.fromkeys(_selector(ref) for ref in _scalar_references(predicate)))
    references = tuple(iter_semantic_references(predicate))
    all_selectors = tuple(dict.fromkeys(_selector(ref) for ref in references))
    records = {key: _matching_records(portfolio, key) for key in all_selectors}
    for key in all_selectors:
        derived = key[1] == "headline" or any(headline_reference(ref) for ref in references if _selector(ref) == key)
        records[key] = tuple(r for r in records[key] if is_headline_record(r) == derived)
    bound: dict[tuple[str, str | None, str | None], SemanticRecord | None] = {}
    parameters: dict[str, str] = {}
    aggregate_cache: dict[tuple, tuple[int | float, int | float] | None] = {}
    branch_cache = {}
    evidence = collection_evidence or {}

    def product_key(record):
        noun, producer, channel = _record_parts(record.semantic_type)
        if channel is None and record.internal_source is not None:
            execution = portfolio.execution(record.internal_source.internal_execution_id)
            channel = execution.broker if execution is not None else None
        return noun + ("@" + producer if producer else "") + (":" + channel if producer and channel else "")

    def empty_products(reference, *, detection_only=False):
        path = substitute(reference.field_path)
        result = set()
        for key, proof in evidence.items():
            if len(key) != 2 and not (detection_only and len(key) == 3 and key[2] == "detections"):
                continue
            owner, qualified = key[:2]
            if owner != portfolio.internal_portfolio_id.value or proof[0] is not True:
                continue
            head, _, field = qualified.partition(".")
            noun, _, qualifiers = head.partition("@")
            producer, _, channel = qualifiers.partition(":")
            if (noun == reference.semantic_type and field == path
                and reference.producer in (None, producer) and reference.channel in (None, channel)):
                result.add(head)
        return result

    def substitute(path):
        if any(name not in parameters for name in re.findall(r"\{([^{}]+)\}", path)):
            return None
        return re.sub(r"\{([^{}]+)\}", lambda match: parameters[match.group(1)], path)

    def matching(reference):
        return records.get(_selector(reference), ())

    def declared_filters():
        from .models import summary_object_identity
        identity = summary_object_identity(portfolio)
        return (_collection_paths().parameter_domain("photometry.{filter}", identity[0])
                if identity else None)

    def ambiguous(reference, matches):
        from .models import summary_object_identity
        identity = summary_object_identity(portfolio)
        candidate = (f"{identity[0]}/{identity[1]}" if identity is not None
                     else portfolio.internal_portfolio_id.value)
        label = reference.qualified_record_type + ("." + reference.field_path if reference.field_path else "")
        message = f"ambiguous_product: candidate={candidate} selector={label} matches={len(matches)}"
        if diagnostics is not None and message not in diagnostics:
            diagnostics.append(message)

    def branch_requirements(collection, paths):
        paths = tuple(paths)
        cache_key = (collection, paths, tuple(sorted(parameters.items())))
        if cache_key in branch_cache:
            return branch_cache[cache_key]
        absolute = collection.ontology_path
        groups, bands = {}, set()
        model = _collection_paths()
        for path in paths:
            full = absolute + ("." + path if path else "")
            for prefix, parameter in model.parameter_scopes(full):
                resolved = substitute(prefix)
                if resolved is None:
                    continue
                if parameter == "filter":
                    bands.add(resolved.rsplit(".", 1)[-1])
                if prefix.startswith(absolute + "."):
                    relative = resolved[len(absolute) + 1:]
                    groups.setdefault(parameter, set()).add(relative)
        result = tuple(tuple(paths) for paths in groups.values()), frozenset(bands)
        branch_cache[cache_key] = result
        return result

    def member(item, groups):
        return all(any(_branch_present(item, path) for path in alternatives) for alternatives in groups)

    def absent_element_branch(operand, element, collection):
        if not isinstance(operand, ElementReference) or collection is None:
            return False
        groups, _ = branch_requirements(collection, (operand.field_path,))
        return not member(element, groups)

    def detection_condition(node, negate=False):
        """A sufficient Boolean proof that every selected member is a detection."""
        if isinstance(node, NotPredicate):
            return detection_condition(node.operand, not negate)
        if isinstance(node, BooleanPredicate):
            values = tuple(detection_condition(child, negate) for child in node.operands)
            conjunction = (node.operator == "and") != negate
            return any(values) if conjunction else all(values)
        if not isinstance(node, ComparisonPredicate) or node.operator not in {"=", "!="}:
            return False
        left, right = node.left, node.right
        if isinstance(right, ElementReference):
            left, right = right, left
        if not isinstance(left, ElementReference) or not isinstance(right, PredicateLiteral) or type(right.value) is not bool:
            return False
        path = left.field_path.split(".")
        if len(path) != 3 or path[0] != "photometry" or path[-1] != "upper_limit":
            return False
        equals = (node.operator == "=") != negate
        return (equals and right.value is False) or (not equals and right.value is True)

    def aggregate(node):
        cache_key = (node, tuple(sorted(parameters.items())))
        if cache_key in aggregate_cache:
            return aggregate_cache[cache_key]
        reference = node.reference
        projection = None
        collection = reference
        if node.function != "count":
            boundary = _collection_paths().array_boundaries(reference.ontology_path)[-1]
            field = boundary.partition(".")[2]
            collection = reference.model_copy(update={"field_path": field})
            projection = reference.field_path[len(field) + 1:]
        detection_only = node.function == "count" and detection_condition(node.condition)
        matches = matching(reference)
        if collection.field_path and len(matches) > 1 and len({product_key(r) for r in matches}) == 1:
            path = substitute(collection.field_path)
            holders = tuple(r for r in matches if path is not None and _lookup(r, path) is not _MISSING)
            # Separate physical calls can deliver sibling arrays of one product.
            # They do not compete for the named array. Multiple holders still do.
            siblings = tuple(r for r in matches if r not in holders and any(
                key != path and _collection_paths().array_boundaries(r.semantic_type + "." + key)
                for key in r.fields
            ))
            if holders and len(holders) + len(siblings) == len(matches):
                matches = holders
            elif not holders and len(siblings) == len(matches) and empty_products(collection, detection_only=detection_only):
                matches = ()  # Empty receipt concerns this array, not sibling histories.
        empties = empty_products(collection, detection_only=detection_only) if collection.field_path else set()
        if empties and (len({product_key(r) for r in matches} | empties) > 1 or len(matches) > 1):
            ambiguous(collection, tuple(matches) + tuple(empties))
            aggregate_cache[cache_key] = None
            return None
        complete, delivered = False, frozenset()
        malformed_array = False
        if not collection.field_path:
            # Record counts never pool lightcurve point representations.
            items = matches if matches else None
        elif len(matches) > 1:
            ambiguous(collection, matches)
            aggregate_cache[cache_key] = None
            return None
        elif not matches:
            items = None
        else:
            record = matches[0]
            path = substitute(collection.field_path)
            if path is None:
                items = None
            else:
                items, shape_valid = _array_members(record, path)
                malformed_array = not shape_valid and _lookup(record, path) is not _MISSING
                proof = evidence.get((record.internal_record_id.value, path), (False, frozenset()))
                complete = proof[0] is True and shape_valid and items is not None
                delivered = frozenset(proof[1])
                if detection_only:
                    scoped = evidence.get((record.internal_record_id.value, path, "detections"))
                    if scoped is not None and scoped[0] is True and shape_valid and items is not None:
                        complete, delivered = True, frozenset(scoped[1])
        if empties and not malformed_array and (items is None or not items):
            items, complete, delivered = (), True, frozenset()
            if detection_only:
                for product in empties:
                    receipt = evidence.get((portfolio.internal_portfolio_id.value,
                                            product + "." + substitute(collection.field_path), "detections"))
                    if receipt is not None and receipt[0] is True:
                        delivered |= frozenset(receipt[1])
        relative_paths = (projection,) if projection is not None else tuple(_element_paths(node.condition, declared_filters()))
        groups, bands = branch_requirements(collection, relative_paths)
        complete = complete and bands <= delivered
        if items is None:
            result = (0, math.inf) if node.function == "count" else (-math.inf, math.inf)
        else:
            items = tuple(item for item in items if member(item, groups))
            if node.function == "count":
                lower = unknown = 0
                for item in items:
                    value = True if node.condition is None else evaluate(node.condition, element=item, collection=collection)
                    lower += value is True
                    unknown += value is None
                result = (lower, lower + unknown if complete else math.inf)
            else:
                known, unknown = [], False
                path = substitute(projection)
                for item in items:
                    value = _lookup(item, path) if path is not None else _MISSING
                    if type(value) is int or type(value) is float and math.isfinite(value):
                        known.append(value)
                    else:
                        unknown = True
                if not known:
                    result = None if complete and not items else (-math.inf, math.inf)
                elif node.function == "min":
                    smallest = min(known)
                    result = (smallest if complete and not unknown else -math.inf, smallest)
                else:
                    largest = max(known)
                    result = (largest, largest if complete and not unknown else math.inf)
        aggregate_cache[cache_key] = result
        return result

    def operand_value(operand, element):
        if isinstance(operand, PredicateLiteral):
            return operand.value
        if isinstance(operand, ElementReference):
            path = substitute(operand.field_path)
            return _lookup(element, path) if element is not None and path is not None else _MISSING
        record = bound.get(_selector(operand))
        if record is None:
            return _MISSING
        path = substitute(operand.field_path)
        if path is None:
            return _MISSING
        reference = operand.model_copy(update={"field_path": path}) if path != operand.field_path else operand
        value = _record_value(record, reference, portfolio)
        if value is _MISSING and path != operand.field_path:
            value = _lookup(record, path)
        return value

    def output_domain(node, element, collection):
        refs = tuple(iter_semantic_references(node.operand, collection))
        reference = next((ref for ref in refs if "{output}" in ref.field_path), None)
        if reference is None:
            return None, None, None
        key = _selector(reference)
        if isinstance(element, SemanticRecord) and collection is not None and _selector(collection) == key:
            record = element
        elif reference.producer is None and reference.channel is None and node.quantifier == "any":
            if key not in bound:
                return None, None, None
            record = bound[key]
        else:
            matches = matching(reference)
            if len(matches) > 1:
                ambiguous(reference, matches)
                return None, None, None
            record = matches[0] if matches else None
        if record is None:
            return None, None, None
        prefix = reference.field_path.partition("{output}")[0].rstrip(".")
        prefix = substitute(prefix)
        if prefix is None:
            return None, None, None
        names = []
        nested = _lookup(record, prefix)
        if isinstance(nested, Mapping):
            names.extend(str(name) for name in nested)
        for path in record.fields:
            if path.startswith(prefix + "."):
                names.append(path[len(prefix) + 1:].split(".", 1)[0])
        domain = tuple(dict.fromkeys(name for name in names if name))
        if node.values is not None:
            if not set(node.values) <= set(domain):
                return None, None, None
            domain = node.values
        return domain, key, record

    def quantify(node, negate, element, collection):
        if node.parameter == "filter":
            domain = declared_filters()
            if node.values is not None:
                domain = node.values if domain is not None and set(node.values) <= set(domain) else None
            key = record = None
        else:
            domain, key, record = output_domain(node, element, collection)
        if not domain:
            return None  # Empty data-derived domains remain unknown under NOT too.
        previous_parameter = parameters.get(node.parameter, _MISSING)
        previous_record = bound.get(key, _MISSING) if key is not None else _MISSING
        conjunction = (node.quantifier == "every") != negate
        unknown = False
        try:
            if key is not None:
                bound[key] = record
            for value in domain:
                parameters[node.parameter] = value
                result = evaluate(node.operand, negate=negate, element=element, collection=collection)
                if result is None:
                    unknown = True
                elif result != conjunction:
                    return result
            return None if unknown else conjunction
        finally:
            if previous_parameter is _MISSING:
                parameters.pop(node.parameter, None)
            else:
                parameters[node.parameter] = previous_parameter
            if key is not None:
                if previous_record is _MISSING:
                    bound.pop(key, None)
                else:
                    bound[key] = previous_record

    def evaluate(node, *, negate=False, element=None, collection=None):
        if isinstance(node, NotPredicate):
            return evaluate(node.operand, negate=not negate, element=element, collection=collection)
        if isinstance(node, QuantifierPredicate):
            return quantify(node, negate, element, collection)
        if isinstance(node, ExistsPredicate) and negate and isinstance(node.reference, SemanticReference):
            # Preserve explicit scalar NOT EXISTS across the whole current view.
            path = substitute(node.reference.field_path)
            if path is None:
                return None
            reference = node.reference.model_copy(update={"field_path": path})
            if "{output}" in node.reference.field_path:
                # A new output quantifier binds one assertion. Preserve the
                # whole-view explicit-absence rule only for existing scalar forms.
                record = bound.get(_selector(node.reference))
                return not (record is not None and _existing_component(
                    record, reference, portfolio, value=operand_value(node.reference, element)))
            return not any(_existing_component(record, reference, portfolio)
                           for record in records[_selector(node.reference)])
        if isinstance(node, ComparisonPredicate):
            left_aggregate = isinstance(node.left, AggregateOperand)
            right_aggregate = isinstance(node.right, AggregateOperand)
            if left_aggregate or right_aggregate:
                selected = node.left if left_aggregate else node.right
                literal = node.right if left_aggregate else node.left
                operation = node.operator if left_aggregate else {
                    "=": "=", "!=": "!=", "<": ">", "<=": ">=", ">": "<", ">=": "<=",
                }[node.operator]
                value = _compare_interval(aggregate(selected), operation, literal.value,
                                          integer=selected.function == "count")
            elif (absent_element_branch(node.left, element, collection)
                  or absent_element_branch(node.right, element, collection)):
                # An absent band branch is a non-member, distinct from a missing
                # scalar within an existing branch, which remains unknown.
                value = False
            elif isinstance(node.right, PredicateLiteral) and isinstance(node.right.value, tuple):
                value = compare_taxa(operand_value(node.left, element), node.right.value, node.operator)
            elif isinstance(node.left, PredicateLiteral) and isinstance(node.left.value, tuple):
                value = compare_taxa(operand_value(node.right, element), node.left.value, node.operator)
            else:
                value = _compare(operand_value(node.left, element), node.operator, operand_value(node.right, element))
        elif isinstance(node, ExistsPredicate):
            if isinstance(node.reference, SemanticReference) and _selector(node.reference) not in bound:
                return None
            if isinstance(node.reference, SemanticReference):
                record = bound.get(_selector(node.reference))
                path = substitute(node.reference.field_path)
                value = (record is not None and path is not None and _existing_component(
                    record, node.reference.model_copy(update={"field_path": path}), portfolio,
                    value=operand_value(node.reference, element)))
            else:
                value = _available(operand_value(node.reference, element))
        elif isinstance(node, BooleanPredicate):
            conjunction = (node.operator == "and") != negate
            unknown = False
            for child in node.operands:
                value = evaluate(child, negate=negate, element=element, collection=collection)
                if value is None:
                    unknown = True
                elif value != conjunction:
                    return value
            return None if unknown else conjunction
        else:
            return None
        return None if value is None else (not value if negate else value)

    def search(index):
        value = evaluate(predicate)
        if value is not None or index == len(selectors):
            return value
        key = selectors[index]
        unknown = False
        try:
            for record in records[key] or (None,):
                bound[key] = record
                value = search(index + 1)
                if value is True:
                    return True
                unknown = unknown or value is None
        finally:
            bound.pop(key, None)
        return None if unknown else False

    return search(0)


def evaluate_portfolio_predicate(
    portfolio: Portfolio, predicate: Predicate, *, diagnostics: list[str] | None = None,
    collection_evidence: Mapping[tuple[str, ...], tuple[bool, frozenset[str]]] | None = None,
) -> bool:
    """Select only established True; retain the existing Boolean caller contract."""
    return evaluate_portfolio_predicate_truth(
        portfolio, predicate, diagnostics=diagnostics, collection_evidence=collection_evidence,
    ) is True


def prune_portfolios(
    portfolios: tuple[Portfolio, ...] | list[Portfolio], predicate: Predicate,
    *, diagnostics: list[str] | None = None,
    collection_evidence=None,
) -> tuple[Portfolio, ...]:
    """Refine existing candidates without changing their scientific records."""
    if any(headline_reference(ref) for ref in iter_semantic_references(predicate)):
        portfolios = tuple(materialize_headlines(p) for p in portfolios)
    return tuple(portfolio for portfolio in portfolios
                 if evaluate_portfolio_predicate(portfolio, predicate, diagnostics=diagnostics,
                                                  collection_evidence=collection_evidence))


__all__ = ["evaluate_portfolio_predicate", "evaluate_portfolio_predicate_truth", "prune_portfolios"]
