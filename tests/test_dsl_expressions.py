import pytest

from alertissimo.dsl import (
    BooleanExpression,
    ComparisonExpression,
    DSLParseError,
    ExistsExpression,
    ExpressionParseError,
    LiteralExpression,
    NotExpression,
    ReferenceExpression,
    expression_grammar_text,
    extract_semantic_record_references,
    iter_references,
    parse_expression,
    parse_surface_script,
    resolve_expression_references,
)


_RECORD_TYPES = frozenset(
    {"summary", "classification", "crossmatch", "lightcurve"}
)


def test_expression_grammar_is_hand_authored_and_predicate_focused():
    grammar = expression_grammar_text()

    assert "comparison: operand COMP_OP operand" in grammar
    assert "exists_expr" in grammar
    assert "AND.3" in grammar and "OR.3" in grammar and "NOT.3" in grammar
    assert "AUTO-GENERATED" not in grammar
    assert "WorkflowIR" not in grammar


def test_comparison_builds_typed_reference_and_literal_nodes():
    expression = parse_expression('best.class = "SN"')

    assert isinstance(expression, ComparisonExpression)
    assert expression.operator == "="
    assert isinstance(expression.left, ReferenceExpression)
    assert expression.left.root == "best"
    assert expression.left.path == ("class",)
    assert isinstance(expression.right, LiteralExpression)
    assert expression.right.value == "SN"


def test_boolean_precedence_and_parentheses_are_structural():
    expression = parse_expression(
        'summary.time.last_mjd > 60000 or '
        '(classification@lc_classifier.best.class = "SN" and not crossmatch exists)'
    )

    assert isinstance(expression, BooleanExpression)
    assert expression.operator == "or"
    assert len(expression.operands) == 2

    conjunction = expression.operands[1]
    assert isinstance(conjunction, BooleanExpression)
    assert conjunction.operator == "and"
    assert isinstance(conjunction.operands[1], NotExpression)
    assert isinstance(conjunction.operands[1].operand, ExistsExpression)


def test_exists_is_accepted_in_prefix_and_postfix_forms():
    prefix = parse_expression("exists crossmatch")
    postfix = parse_expression("crossmatch exists")

    assert isinstance(prefix, ExistsExpression)
    assert isinstance(postfix, ExistsExpression)
    assert prefix.operand.root == "crossmatch"
    assert postfix.operand.root == "crossmatch"


def test_literals_support_numbers_booleans_and_single_quoted_strings():
    expression = parse_expression(
        "probability >= -1.2e-3 and active = true and class_name = 'SN Ia'"
    )

    assert isinstance(expression, BooleanExpression)
    values = [
        node.right.value
        for node in expression.operands
        if isinstance(node, ComparisonExpression)
        and isinstance(node.right, LiteralExpression)
    ]
    assert values == [-0.0012, True, "SN Ia"]


def test_scoped_reference_resolution_inherits_product_producer_and_channel():
    expression = parse_expression(
        'best.class = "SN" and best.probability >= 0.8'
    )

    resolved = resolve_expression_references(
        expression,
        _RECORD_TYPES,
        scoped_noun="classification",
        scoped_producer="lc_classifier",
        scoped_channel="alerce",
    )

    refs = tuple(iter_references(resolved))
    assert [ref.field_path for ref in refs] == [
        "best.class",
        "best.probability",
    ]
    assert all(ref.record_type == "classification" for ref in refs)
    assert all(ref.producer == "lc_classifier" for ref in refs)
    assert all(ref.channel == "alerce" for ref in refs)
    assert all(ref.resolution == "scoped" for ref in refs)


def test_explicit_semantic_reference_resolves_absolutely():
    expression = parse_expression(
        'classification@lc_classifier.best.class = "SN"'
    )

    resolved = resolve_expression_references(expression, _RECORD_TYPES)
    reference = tuple(iter_references(resolved))[0]

    assert reference.record_type == "classification"
    assert reference.producer == "lc_classifier"
    assert reference.channel is None
    assert reference.field_path == "best.class"
    assert reference.resolution == "absolute"


def test_record_root_without_qualifier_resolves_absolutely():
    expression = parse_expression("summary.time.last_mjd > 60000")

    resolved = resolve_expression_references(expression, _RECORD_TYPES)
    reference = tuple(iter_references(resolved))[0]

    assert reference.record_type == "summary"
    assert reference.field_path == "time.last_mjd"


def test_bare_record_noun_comparison_does_not_imply_best_or_scalar_semantics():
    expression = parse_expression('classification = "SN"')

    resolved = resolve_expression_references(expression, _RECORD_TYPES)
    reference = tuple(iter_references(resolved))[0]

    assert reference.record_type is None
    assert reference.resolution == "unresolved"


def test_bare_nonontology_alias_remains_unresolved_for_later_semantic_aliasing():
    expression = parse_expression("decline_rate > 0.3")

    resolved = resolve_expression_references(expression, _RECORD_TYPES)
    reference = tuple(iter_references(resolved))[0]

    assert reference.record_type is None
    assert reference.resolution == "unresolved"


def test_semantic_dependency_extraction_is_ast_based_and_deduplicated():
    refs = extract_semantic_record_references(
        'classification@lc_classifier.best.class = "SN" and '
        "classification@lc_classifier.best.probability >= 0.8",
        _RECORD_TYPES,
    )

    assert len(refs) == 1
    assert refs[0].noun == "classification"
    assert refs[0].producer == "lc_classifier"


def test_invalid_expression_syntax_is_rejected_by_expression_parser():
    with pytest.raises(ExpressionParseError):
        parse_expression("summary.time.last_mjd >>> 60000")


def test_surface_where_uses_expression_grammar_as_actual_syntax_gate():
    with pytest.raises(DSLParseError, match="invalid expression syntax"):
        parse_surface_script(
            "objects from lsst\n"
            "where summary.time.last_mjd >>> 60000\n"
        )


def test_scoped_with_predicate_uses_expression_grammar_as_actual_syntax_gate():
    with pytest.raises(DSLParseError, match="invalid expression syntax"):
        parse_surface_script(
            "objects from lsst via alerce\n"
            "with classification from lc_classifier:\n"
            "    best.probability >>> 0.8\n"
        )
