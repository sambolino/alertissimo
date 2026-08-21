import pytest

from alertissimo.dsl import (
    DSLParseError,
    SurfaceValidationReport,
    extract_semantic_record_references,
    grammar_text,
    parse_surface_script,
    validate_surface_semantics,
)


class _FakeSemanticPaths:
    record_types = frozenset(
        {"summary", "lightcurve", "crossmatch", "classification", "color_magnitude"}
    )

    def is_valid(self, semantic_path: str) -> bool:
        return semantic_path in {
            "summary@dsl.photometry.r.mag.mean",
            "classification@dsl.best.class",
            "classification@dsl.best.probability",
        }


def test_formal_grammar_is_hand_authored_and_requirement_centric():
    grammar = grammar_text()

    assert "candidate_statement" in grammar
    assert '"objects"i "from"i' in grammar
    assert "requirement: PRODUCT from_clause? via_clause? using_clause?" in grammar
    assert "match_on" in grammar
    assert "WITHIN expresses temporal extent" in grammar
    assert "INSIDE expresses spatial extent" in grammar
    assert "_INDENT" in grammar and "_DEDENT" in grammar
    assert "with_colon" in grammar and "with_where" in grammar
    assert "VERB" not in grammar
    assert "AUTO-GENERATED" not in grammar


def test_production_parser_enforces_formal_qualifier_order():
    with pytest.raises(DSLParseError):
        parse_surface_script(
            "objects from lsst\nwith crossmatch via fink from gaia\n"
        )


def test_static_validation_accepts_ontology_product_but_defers_capability():
    surface = parse_surface_script(
        "objects from lsst via fink\n"
        "with crossmatch from erosita via antares\n"
        "match from icecube on position inside 2deg\n"
    )

    report = validate_surface_semantics(
        surface,
        semantic_paths=_FakeSemanticPaths(),
    )

    assert isinstance(report, SurfaceValidationReport)
    assert report.is_valid


def test_scoped_classification_paths_are_validated_relative_to_requirement():
    surface = parse_surface_script(
        """objects from lsst via alerce
with classification from lc_classifier:
    best.class = "SN"
    best.probability >= 0.8
"""
    )

    report = validate_surface_semantics(surface, semantic_paths=_FakeSemanticPaths())

    assert report.is_valid


def test_invalid_scoped_path_fails_ontology_validation():
    surface = parse_surface_script(
        """objects from lsst via alerce
with classification from lc_classifier:
    best.nonsense = "SN"
"""
    )

    report = validate_surface_semantics(surface, semantic_paths=_FakeSemanticPaths())

    assert not report.is_valid
    assert report.errors[0].code == "invalid_requirement_predicate_path"


def test_fully_qualified_general_where_exposes_implicit_semantic_dependency():
    condition = (
        'classification@lc_classifier.best.class = "SN" and '
        "classification@lc_classifier.best.probability >= 0.8"
    )

    refs = extract_semantic_record_references(
        condition, _FakeSemanticPaths.record_types
    )

    assert len(refs) == 1
    assert refs[0].noun == "classification"
    assert refs[0].producer == "lc_classifier"
    assert refs[0].channel is None


def test_static_validation_accepts_fully_qualified_general_where():
    surface = parse_surface_script(
        "objects from lsst via alerce\n"
        'where classification@lc_classifier.best.class = "SN" and '
        "classification@lc_classifier.best.probability >= 0.8\n"
    )

    assert validate_surface_semantics(
        surface, semantic_paths=_FakeSemanticPaths()
    ).is_valid


def test_static_validation_resolves_hyphenated_record_noun_in_phrase():
    surface = parse_surface_script(
        "objects from lsst\nwith color-magnitude g-r vs r\n"
    )

    report = validate_surface_semantics(surface, semantic_paths=_FakeSemanticPaths())

    assert report.is_valid


def test_static_validation_rejects_unknown_requirement_product():
    surface = parse_surface_script("objects from lsst\nwith bananas\n")

    report = validate_surface_semantics(surface, semantic_paths=_FakeSemanticPaths())

    assert not report.is_valid
    assert report.errors[0].code == "unknown_requirement_product"


def test_static_validation_rejects_invalid_explicit_order_path():
    surface = parse_surface_script(
        "objects from lsst\norder by summary.photometry.r.mag.maximum\n"
    )

    report = validate_surface_semantics(surface, semantic_paths=_FakeSemanticPaths())

    assert not report.is_valid
    assert report.errors[0].code == "invalid_order_path"


def test_static_validation_resolves_spaced_compound_record_noun():
    surface = parse_surface_script(
        "objects from lsst\nwith color magnitude g-r vs r\n"
    )

    report = validate_surface_semantics(surface, semantic_paths=_FakeSemanticPaths())

    assert report.is_valid


def test_inline_comment_is_not_part_of_requirement_product():
    surface = parse_surface_script(
        "objects from lsst\nwith crossmatch from gaia # catalog enrichment\n"
    )

    assert surface.clauses[0].product == "crossmatch"
    assert surface.clauses[0].source == "gaia"
