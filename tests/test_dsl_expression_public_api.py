from alertissimo.dsl import (
    BooleanExpression,
    ExistsExpression,
    parse_expression,
)


def test_expression_public_api_parses_boolean_existence_predicate():
    expression = parse_expression(
        "classification exists and summary.time.last_mjd > 60000"
    )

    assert isinstance(expression, BooleanExpression)
    assert isinstance(expression.operands[0], ExistsExpression)
