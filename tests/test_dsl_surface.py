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
        parse_surface_script(
            """
            objects from lsst
            objects from ztf
            """
        )


def test_first_pass_preserves_ordered_selection_and_enrichment_clauses():
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
    assert result.clauses[4].source is None

    crossmatch = result.clauses[5]
    assert isinstance(crossmatch, RequirementClause)
    assert crossmatch.product == "crossmatch"
    assert crossmatch.source == "gaia"
    assert crossmatch.via == "fink"

    assert isinstance(result.clauses[6], OrderByClause)
    assert result.clauses[6].expression == "summary.photometry.r.mag.mean"
    assert result.clauses[6].direction == "asc"

    assert isinstance(result.clauses[7], RankedByClause)
    assert result.clauses[7].criterion == "chance coincidence"
    assert result.clauses[7].direction is None


def test_requirement_can_select_explicit_method_without_changing_candidate_scope():
    result = parse_surface_script(
        """
        objects from lsst
            with classification using alertissimo:clasMeV2
        """
    )

    requirement = result.clauses[0]
    assert isinstance(requirement, RequirementClause)
    assert requirement.product == "classification"
    assert requirement.method == "alertissimo:clasMeV2"
    assert result.candidates.origins == ("lsst",)


def test_filter_then_with_means_refine_then_enrich_in_order():
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


def test_where_is_not_allowed_after_filter():
    with pytest.raises(
        DSLParseError, match="where belongs to the initial candidate pass"
    ):
        parse_surface_script(
            """
            objects from lsst
            filter decline_rate > 0.3
            where classification = "SN Ia"
            """
        )


def test_match_can_associate_candidate_origins_without_external_counterpart():
    result = parse_surface_script(
        """
        objects from lsst, ztf
            match on position within 1arcsec
        """
    )

    match = result.clauses[0]
    assert isinstance(match, MatchClause)
    assert match.counterpart_origin is None
    assert match.on == "position within 1arcsec"
    assert result.candidates.origins == ("lsst", "ztf")


def test_match_can_introduce_external_counterpart_without_mutating_candidate_origins():
    result = parse_surface_script(
        """
        objects from lsst via fink
        filter classification = "SN"
            match from icecube within 3d on position within 2deg
        """
    )

    match = result.clauses[1]
    assert isinstance(match, MatchClause)
    assert match.counterpart_origin == "icecube"
    assert match.within.value == 3
    assert match.within.unit == "d"
    assert match.on == "position within 2deg"
    assert result.candidates.origins == ("lsst",)
    assert result.candidates.broker == "fink"


def test_explicit_within_window_is_preserved_without_resolving_runtime_time():
    result = parse_surface_script(
        """
        objects from lsst
            within 2026-08-01, 2026-08-15
        """
    )

    window = result.clauses[0]
    assert isinstance(window, WithinClause)
    assert window.start == "2026-08-01"
    assert window.end == "2026-08-15"
    assert window.duration is None
    assert window.relative_to is None


def test_latest_requires_positive_count():
    with pytest.raises(DSLParseError, match="positive integer"):
        parse_surface_script(
            """
            objects from lsst
            latest 0
            """
        )


def test_unknown_clause_is_rejected_with_line_number():
    with pytest.raises(DSLParseError, match=r"Line 2: unknown DSL clause"):
        parse_surface_script("objects from lsst\nclassify everything")
