"""Collection syntax is representable and validated, but not executable yet."""

import pytest
from pydantic import TypeAdapter

from alertissimo.api import validate_dsl
from alertissimo.data_layer.semantic_model import SemanticPathModel
from alertissimo.dsl import DSLParseError, parse_expression, parse_surface_script, validate_surface_semantics
from alertissimo.dsl.expression import (
    AggregateExpression, Expression, QuantifierExpression, iter_references, map_references,
)
from alertissimo.dsl.predicate_lowering import lower_expression_predicate
from alertissimo.orchestration.ir.predicates import (
    AggregateOperand, ElementReference, iter_semantic_references,
)


PREFIX = "objects from ztf via fink\n"


@pytest.fixture(scope="module")
def paths():
    return SemanticPathModel.from_ontology()


@pytest.mark.parametrize("source", [
    "count(measurement@ztf:fink where quality.real_bogus > 0.9) >= 5",
    "count(lightcurve@ztf:fink.points) = 0",
    "min(lightcurve.points.photometry.g.psf.mag) < 19",
    "max(lightcurve.points.photometry.r.psf.mag) >= 20",
    "5 <= count(lightcurve.points)",
    "for every {filter}: (count(lightcurve.points where photometry.{filter}.upper_limit = false) >= 5)",
    "for any {filter} in [g, r]: (min(lightcurve.points.photometry.{filter}.psf.mag) < 19)",
    "for any {output}: (classification.assessment.{output}.probability >= 0.8)",
    "for every {output}: (classification@lc_classifier:alerce.assessment.{output}.probability >= 0.8)",
])
def test_agreed_forms_validate_but_are_explicitly_not_runnable(source):
    result = validate_dsl(PREFIX + "filter " + source, continue_from=None)
    assert result.is_valid, result
    assert not result.is_runnable
    assert result.capabilities.deferred
    assert "collection admission is pending" in result.capabilities.deferred[0].reason


def test_multiline_quantifier_comments_and_json_round_trip(paths):
    source = """objects from ztf via fink
    with lightcurve via fink
    filter for every {filter} in [g, r]: (
        # The repetition domain is declared, never inferred from this payload.
        count(lightcurve@ztf:fink.points
              where photometry.{filter}.psf.mag exists
                and photometry.{filter}.upper_limit = false) >= 5
    )
"""
    surface = parse_surface_script(source)
    assert validate_surface_semantics(surface).is_valid
    expression = parse_expression(surface.clauses[-1].condition)
    assert isinstance(expression, QuantifierExpression)
    assert isinstance(expression.operand.left, AggregateExpression)
    adapter = TypeAdapter(Expression)
    assert adapter.validate_json(adapter.dump_json(expression)) == expression
    assert map_references(expression, lambda ref: ref) == expression
    predicate = lower_expression_predicate(expression, paths.record_types, origins=("ztf",))
    assert isinstance(predicate.operand.left, AggregateOperand)
    assert isinstance(predicate.operand.left.condition.operands[0].reference, ElementReference)
    fields = [ref.field_path for ref in iter_semantic_references(predicate)]
    assert fields == ["points", "points.photometry.{filter}.psf.mag",
                      "points.photometry.{filter}.upper_limit"]
    refs = list(iter_references(expression))
    assert refs[1].path == ("points", "photometry", "{filter}", "psf", "mag")


def test_multiline_error_coordinates_refer_to_original_indented_source():
    lines = ["objects from ztf via fink", "    filter for any {filter}: (",
             "        min(lightcurve.points.photometry.{filter}.psf.mag) < @", "    )"]
    with pytest.raises(DSLParseError) as error:
        parse_surface_script("\n".join(lines))
    assert error.value.line == 3
    assert error.value.column == lines[2].index("@") + 1


def test_quoted_parentheses_and_comment_markers_do_not_change_group_depth():
    source = PREFIX + 'filter classification@fink.best.class = "AGN (#1)"'
    surface = parse_surface_script(source)
    assert surface.clauses[0].condition.endswith('"AGN (#1)"')


@pytest.mark.parametrize("source", [
    "count(lightcurve.points) >=\n5",
    "for every {filter}:\n(count(lightcurve.points) >= 5)",
    "count(lightcurve.points as p) > 1",
    "count(lightcurve.points) > $number",
    "exists count(lightcurve.points)",
    "count(lightcurve.points) exists",
    "count(lightcurve.points) > min(lightcurve.points.time.mjd)",
    "count(lightcurve.points) > summary.detection_count",
    "count(lightcurve.points) > true",
    "for any {filter} in []: (count(lightcurve.points) > 1)",
    "for any {filter} in [g, g]: (count(lightcurve.points) > 1)",
])
def test_unagreed_or_structurally_invalid_syntax_is_rejected(source):
    with pytest.raises(DSLParseError):
        parse_surface_script(PREFIX + "filter " + source)


@pytest.mark.parametrize("source", [
    "count(lightcurve.points.time.mjd) > 1",
    "min(lightcurve.points.photometry.g.psf) < 19",
    "max(summary.time.last_mjd) > 60000",
    "count(lightcurve.points where measurement@ztf:fink.quality.real_bogus > 0.9) > 1",
    "count(lightcurve.points where summary.detection_count > 1) > 1",
    "count(lightcurve.points where photometry.{filter}.psf.mag < 19) > 1",
    "for any {filter} in [u]: (count(lightcurve.points where photometry.{filter}.psf.mag < 19) > 1)",
    "for every {output}: (classification.assessment.{output}.probability > 0.8)",
    "for any {filter}: (for every {filter}: (min(lightcurve.points.photometry.{filter}.psf.mag) < 19))",
    "for any {filter}: (classification.assessment.{output}.probability > 0.8)",
])
def test_ontology_scope_and_domains_reject_invalid_programs(source):
    result = validate_dsl(PREFIX + "filter " + source, continue_from=None)
    assert not result.is_valid


def test_static_product_ambiguity_requires_existing_qualifier():
    source = PREFIX + "with lightcurve via fink\nwith lightcurve via lasair\nfilter count(lightcurve.points) >= 5"
    result = validate_dsl(source, continue_from=None)
    assert not result.is_valid
    assert any("qualify" in issue.message for issue in result.semantic.errors)
    qualified = source.replace("count(lightcurve.points)", "count(lightcurve@ztf:fink.points)")
    result = validate_dsl(qualified, continue_from=None)
    assert result.is_valid
    assert not result.is_runnable


def test_distinct_nested_parameters_are_allowed_without_shadowing():
    source = ("for any {filter}: (for any {output}: ("
              "min(lightcurve.points.photometry.{filter}.psf.mag) < 19 and "
              "classification.assessment.{output}.probability >= 0.8))")
    assert validate_dsl(PREFIX + "filter " + source, continue_from=None).is_valid


def test_lsst_explicit_filter_members_use_lsst_domain():
    source = "objects from lsst via alerce\nfilter for any {filter} in [u, y]: (min(lightcurve.points.photometry.{filter}.psf.mag) < 19)"
    result = validate_dsl(source, continue_from=None)
    assert result.is_valid
    assert not result.is_runnable


def test_comments_between_function_tokens_inside_an_open_body():
    source = PREFIX + """filter for any {filter}: (
        min # comment before the argument parenthesis
        (lightcurve.points.photometry.{filter}.psf.mag) < 19
    )"""
    result = validate_dsl(source, continue_from=None)
    assert result.is_valid
    assert not result.is_runnable
