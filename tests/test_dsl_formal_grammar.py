import pytest

from alertissimo.dsl import (
    DSLParseError,
    SurfaceValidationReport,
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
            "classification@dsl.best.probability",
        }


def test_formal_grammar_is_hand_authored_and_requirement_centric():
    grammar = grammar_text()

    assert "candidate_statement" in grammar
    assert '"objects"i "from"i' in grammar
    assert "requirement: PRODUCT from_clause? via_clause? using_clause?" in grammar
    assert "VERB" not in grammar
    assert "AUTO-GENERATED" not in grammar


def test_production_parser_enforces_formal_qualifier_order():
    with pytest.raises(DSLParseError):
        parse_surface_script(
            "objects from lsst\nwith crossmatch via fink from gaia\n"
        )


def test_static_validation_accepts_ontology_product_but_defers_capability():
    surface = parse_surface_script(
        """
        objects from lsst via fink
        with crossmatch from erosita via antares
        match from icecube on position within 2deg
        """
    )

    report = validate_surface_semantics(
        surface,
        semantic_paths=_FakeSemanticPaths(),
    )

    assert isinstance(report, SurfaceValidationReport)
    assert report.is_valid


def test_static_validation_resolves_hyphenated_record_noun_in_phrase():
    surface = parse_surface_script(
        "objects from lsst\nwith color-magnitude g-r vs r\n"
    )

    report = validate_surface_semantics(
        surface,
        semantic_paths=_FakeSemanticPaths(),
    )

    assert report.is_valid


def test_static_validation_rejects_unknown_requirement_product():
    surface = parse_surface_script("objects from lsst\nwith bananas\n")

    report = validate_surface_semantics(
        surface,
        semantic_paths=_FakeSemanticPaths(),
    )

    assert not report.is_valid
    assert report.errors[0].code == "unknown_requirement_product"


def test_static_validation_rejects_invalid_explicit_order_path():
    surface = parse_surface_script(
        "objects from lsst\norder by summary.photometry.r.mag.maximum\n"
    )

    report = validate_surface_semantics(
        surface,
        semantic_paths=_FakeSemanticPaths(),
    )

    assert not report.is_valid
    assert report.errors[0].code == "invalid_order_path"


def test_static_validation_resolves_spaced_compound_record_noun():
    surface = parse_surface_script(
        "objects from lsst\nwith color magnitude g-r vs r\n"
    )

    report = validate_surface_semantics(
        surface,
        semantic_paths=_FakeSemanticPaths(),
    )

    assert report.is_valid


def test_inline_comment_is_not_part_of_requirement_product():
    surface = parse_surface_script(
        "objects from lsst\nwith crossmatch from gaia # catalog enrichment\n"
    )

    assert surface.clauses[0].product == "crossmatch"
    assert surface.clauses[0].source == "gaia"
