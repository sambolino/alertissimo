import pytest

from alertissimo.dsl.surface import (
    DSLParseError,
    FilterClause,
    InsideClause,
    LatestClause,
    MatchClause,
    OrderByClause,
    RankedByClause,
    RequirementClause,
    WhereClause,
    WithinClause,
    parse_surface_script,
)


def test_objects_require_fixed_candidate_origins_and_optional_default_broker():
    result = parse_surface_script("objects from lsst, ztf via fink")

    assert result.candidates.origins == ("lsst", "ztf")
    assert result.candidates.broker == "fink"
    assert result.clauses == ()


def test_objects_without_origin_are_rejected():
    with pytest.raises(DSLParseError, match="first statement must be"):
        parse_surface_script("objects via fink")


def test_candidate_origins_cannot_be_redeclared_later():
    with pytest.raises(DSLParseError, match="candidate origins are fixed"):
        parse_surface_script("objects from lsst\nobjects from ztf\n")


def test_first_pass_preserves_selection_enrichment_and_view_clauses():
    result = parse_surface_script(
        """
        objects from lsst via fink
            inside (34, 33, 0.5deg)
            within 7d
            latest 100
            where classification = "SN Ia"
            with lightcurve
            with crossmatch from gaia via fink
            order by summary.photometry.r.mag.mean asc
            ranked by chance coincidence
        """
    )

    assert isinstance(result.clauses[0], InsideClause)
    assert result.clauses[0].radius.value == 0.5
    assert result.clauses[0].radius.unit == "deg"
    assert isinstance(result.clauses[1], WithinClause)
    assert result.clauses[1].relative_to == "now"
    assert result.clauses[1].duration.value == 7
    assert result.clauses[1].duration.unit == "d"
    assert isinstance(result.clauses[2], LatestClause)
    assert result.clauses[2].count == 100
    assert isinstance(result.clauses[3], WhereClause)
    assert result.clauses[3].condition == 'classification = "SN Ia"'
    assert isinstance(result.clauses[4], RequirementClause)
    assert result.clauses[4].product == "lightcurve"
    crossmatch = result.clauses[5]
    assert isinstance(crossmatch, RequirementClause)
    assert crossmatch.source == "gaia"
    assert crossmatch.via == "fink"
    assert isinstance(result.clauses[6], OrderByClause)
    assert result.clauses[6].direction == "asc"
    assert isinstance(result.clauses[7], RankedByClause)


def test_requirement_can_select_explicit_method_without_changing_candidate_scope():
    result = parse_surface_script(
        "objects from lsst\nwith classification using alertissimo:clasMeV2\n"
    )

    requirement = result.clauses[0]
    assert isinstance(requirement, RequirementClause)
    assert requirement.product == "classification"
    assert requirement.method == "alertissimo:clasMeV2"
    assert result.candidates.origins == ("lsst",)


def test_complete_multiline_script_does_not_require_a_final_newline():
    result = parse_surface_script(
        "objects from ztf via lasair\n"
        "    inside (124.87996115142856, -6.0205001, 5arcsec)\n"
        "    with lightcurve via fink\n"
        "    with lightcurve via lasair"
    )

    assert isinstance(result.clauses[0], InsideClause)
    assert [clause.via for clause in result.clauses[1:]] == ["fink", "lasair"]


def test_colon_scopes_multiple_conjunctive_predicates_to_with():
    result = parse_surface_script(
        """objects from lsst via alerce
with classification from lc_classifier:
    best.class = "SN"
    best.probability >= 0.8
"""
    )

    requirement = result.clauses[0]
    assert isinstance(requirement, RequirementClause)
    assert requirement.product == "classification"
    assert requirement.source == "lc_classifier"
    assert requirement.predicates == (
        'best.class = "SN"',
        "best.probability >= 0.8",
    )


def test_nested_where_is_equivalent_single_requirement_predicate():
    result = parse_surface_script(
        """objects from lsst via alerce
    with classification from lc_classifier
        where best.class = "LPV" and best.probability >= 0.8
"""
    )

    requirement = result.clauses[0]
    assert isinstance(requirement, RequirementClause)
    assert requirement.predicates == (
        'best.class = "LPV" and best.probability >= 0.8',
    )


def test_filter_then_with_remains_top_level_when_indentation_is_cosmetic():
    result = parse_surface_script(
        """
        objects from lsst via fink
            within 7d
        filter decline_rate > 0.3
            with crossmatch from erosita via antares
        """
    )

    assert isinstance(result.clauses[1], FilterClause)
    requirement = result.clauses[2]
    assert isinstance(requirement, RequirementClause)
    assert requirement.source == "erosita"
    assert requirement.via == "antares"
    assert result.candidates.origins == ("lsst",)
    assert result.candidates.broker == "fink"


def test_only_one_general_where_is_allowed():
    with pytest.raises(DSLParseError, match="only one general where"):
        parse_surface_script(
            "objects from lsst\nwhere x = 1\nwhere y = 2\n"
        )


def test_general_where_is_not_allowed_after_filter():
    with pytest.raises(
        DSLParseError, match="where belongs to the initial candidate pass"
    ):
        parse_surface_script(
            "objects from lsst\nfilter decline_rate > 0.3\nwhere x = 1\n"
        )


def test_match_can_associate_candidate_origins_without_external_counterpart():
    result = parse_surface_script(
        "objects from lsst, ztf\nmatch on position inside 1arcsec\n"
    )

    match = result.clauses[0]
    assert isinstance(match, MatchClause)
    assert match.counterpart_origin is None
    assert match.on == "position inside 1arcsec"
    assert result.candidates.origins == ("lsst", "ztf")


def test_match_temporal_within_and_spatial_inside_remain_distinct():
    result = parse_surface_script(
        "objects from lsst via fink\n"
        "filter classification = \"SN\"\n"
        "match from icecube within 3d on position inside 2deg\n"
    )

    match = result.clauses[1]
    assert isinstance(match, MatchClause)
    assert match.counterpart_origin == "icecube"
    assert match.within.value == 3
    assert match.within.unit == "d"
    assert match.on == "position inside 2deg"
    assert result.candidates.origins == ("lsst",)


def test_explicit_within_window_is_preserved_without_resolving_runtime_time():
    result = parse_surface_script(
        "objects from lsst\nwithin 2026-08-01, 2026-08-15\n"
    )

    window = result.clauses[0]
    assert isinstance(window, WithinClause)
    assert window.start == "2026-08-01"
    assert window.end == "2026-08-15"
    assert window.duration is None
    assert window.relative_to is None


def test_latest_requires_positive_count():
    with pytest.raises(DSLParseError, match="positive integer"):
        parse_surface_script("objects from lsst\nlatest 0\n")


def test_unknown_clause_is_rejected_with_line_number():
    with pytest.raises(DSLParseError, match=r"Line 2: unknown DSL clause"):
        parse_surface_script("objects from lsst\nclassify everything")
