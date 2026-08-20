from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraph,
    EndpointCapability,
    SemanticRecordCapability,
    build_capability_graph,
)
from alertissimo.dsl import (
    SurfaceCapabilityStatus,
    parse_surface_script,
    validate_surface_capabilities,
)


class _FakeSemanticPaths:
    record_types = frozenset(
        {
            "summary",
            "lightcurve",
            "crossmatch",
            "classification",
            "color_magnitude",
            "data_product",
        }
    )

    def is_valid(self, semantic_path: str) -> bool:
        return True


def _endpoint(
    broker: str,
    origin: str,
    endpoint: str,
    *operations: str,
) -> EndpointCapability:
    return EndpointCapability(
        broker=broker,
        origin=origin,
        endpoint=endpoint,
        path=f"/{endpoint}",
        method="GET",
        operation_types=tuple(operations),
        params=(),
        server_filters=(),
        projection_param=None,
        supports_projection=False,
        output_type="array",
    )


def _record(
    broker: str,
    origin: str,
    semantic_record_type: str,
    *endpoints: str,
) -> SemanticRecordCapability:
    return SemanticRecordCapability(
        broker=broker,
        origin=origin,
        semantic_record_type=semantic_record_type,
        endpoints=tuple(endpoints),
        fields=(),
    )


def _graph() -> CapabilityGraph:
    endpoints = (
        _endpoint("fink", "lsst", "objects", "object_summary"),
        _endpoint("fink", "lsst", "conesearch", "spatial_search"),
        _endpoint("fink", "lsst", "sources", "lightcurve"),
        _endpoint("fink", "ztf", "objects", "object_summary"),
        _endpoint("antares", "ztf", "object", "object_lookup"),
        _endpoint("antares", "ztf", "cone", "cone_search"),
        _endpoint("lasair", "ztf", "object", "object_lookup"),
    )
    records = (
        _record("fink", "lsst", "summary@lsst:fink", "objects", "conesearch"),
        _record("fink", "lsst", "classification@fink", "objects"),
        _record("fink", "ztf", "summary@ztf:fink", "objects"),
        _record("antares", "ztf", "summary@ztf:antares", "object", "cone"),
        _record("antares", "ztf", "crossmatch@gaia:antares", "object"),
        _record("lasair", "ztf", "summary@ztf:lasair", "object"),
        _record("lasair", "ztf", "crossmatch@{producer}:lasair", "object"),
    )
    return CapabilityGraph(
        endpoint_capabilities=endpoints,
        payload_capabilities=(),
        field_mapping_capabilities=(),
        transform_capabilities=(),
        semantic_record_capabilities=records,
    )


def _validate(script: str):
    return validate_surface_capabilities(
        parse_surface_script(script),
        graph=_graph(),
        semantic_paths=_FakeSemanticPaths(),
    )


def test_requirement_inherits_default_broker_and_matches_qualified_record():
    report = _validate(
        "objects from ztf via antares\n"
        "with crossmatch from gaia\n"
    )

    requirement = next(
        check for check in report.checks if check.subject == "requirement"
    )
    assert report.status is SurfaceCapabilityStatus.SUPPORTED
    assert requirement.origin == "ztf"
    assert requirement.broker == "antares"
    assert requirement.producer == "gaia"
    assert {
        evidence.semantic_record_type for evidence in requirement.evidence
    } == {"crossmatch@gaia:antares"}


def test_requirement_via_overrides_broker_but_never_candidate_origin():
    report = _validate(
        "objects from ztf via fink\n"
        "with crossmatch from gaia via antares\n"
    )

    requirement = next(
        check for check in report.checks if check.subject == "requirement"
    )
    assert requirement.status is SurfaceCapabilityStatus.SUPPORTED
    assert requirement.origin == "ztf"
    assert requirement.broker == "antares"
    assert {evidence.origin for evidence in requirement.evidence} == {"ztf"}


def test_missing_qualified_producer_is_unsupported():
    report = _validate(
        "objects from ztf via antares\n"
        "with crossmatch from erosita\n"
    )

    requirement = next(
        check for check in report.checks if check.subject == "requirement"
    )
    assert requirement.status is SurfaceCapabilityStatus.UNSUPPORTED
    assert report.status is SurfaceCapabilityStatus.UNSUPPORTED


def test_dynamic_producer_mapping_is_deferred_not_treated_as_wildcard():
    report = _validate(
        "objects from ztf via lasair\n"
        "with crossmatch from gaia\n"
    )

    requirement = next(
        check for check in report.checks if check.subject == "requirement"
    )
    assert requirement.status is SurfaceCapabilityStatus.DEFERRED
    assert {
        evidence.semantic_record_type for evidence in requirement.evidence
    } == {"crossmatch@{producer}:lasair"}


def test_lightcurve_can_be_supported_by_registered_operation_fallback():
    report = _validate(
        "objects from lsst via fink\n"
        "with lightcurve\n"
    )

    requirement = next(
        check for check in report.checks if check.subject == "requirement"
    )
    assert requirement.status is SurfaceCapabilityStatus.SUPPORTED
    assert requirement.evidence[0].endpoints == ("sources",)


def test_explicit_algorithm_is_deferred_to_local_method_capabilities():
    report = _validate(
        "objects from ztf via antares\n"
        "with classification using alertissimo:clasMeV2\n"
    )

    requirement = next(
        check for check in report.checks if check.subject == "requirement"
    )
    assert requirement.status is SurfaceCapabilityStatus.DEFERRED


def test_inside_requires_registered_spatial_object_capability():
    report = _validate(
        "objects from lsst via fink\n"
        "inside (34, 33, 0.5deg)\n"
    )

    candidate = next(
        check for check in report.checks if check.subject == "candidates"
    )
    assert candidate.status is SurfaceCapabilityStatus.SUPPORTED
    assert candidate.evidence[0].endpoints == ("conesearch",)


def test_each_fixed_candidate_origin_is_checked_independently():
    report = _validate("objects from lsst, ztf via antares\n")

    candidates = [
        check for check in report.checks if check.subject == "candidates"
    ]
    assert [(check.origin, check.status) for check in candidates] == [
        ("lsst", SurfaceCapabilityStatus.UNSUPPORTED),
        ("ztf", SurfaceCapabilityStatus.SUPPORTED),
    ]


def test_match_counterpart_checks_external_origin_without_mutating_candidates():
    report = _validate(
        "objects from lsst via fink\n"
        "match from icecube on position within 2deg\n"
    )

    counterpart = next(
        check for check in report.checks if check.subject == "match_counterpart"
    )
    local = next(
        check for check in report.checks if check.subject == "match_local"
    )
    assert counterpart.origin == "icecube"
    assert counterpart.status is SurfaceCapabilityStatus.UNSUPPORTED
    assert local.status is SurfaceCapabilityStatus.DEFERRED


def test_real_registry_exposes_exact_gaia_crossmatch_via_antares_ztf():
    graph = build_capability_graph()
    surface = parse_surface_script(
        "objects from ztf via antares\n"
        "with crossmatch from gaia\n"
    )

    report = validate_surface_capabilities(surface, graph=graph)

    requirement = next(
        check for check in report.checks if check.subject == "requirement"
    )
    assert requirement.status is SurfaceCapabilityStatus.SUPPORTED
    assert "crossmatch@gaia:antares" in {
        evidence.semantic_record_type for evidence in requirement.evidence
    }


def test_real_registry_rejects_unregistered_erosita_crossmatch_via_antares():
    graph = build_capability_graph()
    surface = parse_surface_script(
        "objects from ztf via antares\n"
        "with crossmatch from erosita\n"
    )

    report = validate_surface_capabilities(surface, graph=graph)

    requirement = next(
        check for check in report.checks if check.subject == "requirement"
    )
    assert requirement.status is SurfaceCapabilityStatus.UNSUPPORTED
