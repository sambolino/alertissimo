"""Crossmatch retrieval must be selected by semantic capability, not payload accident."""

import pytest

from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraph,
    EndpointCapability,
    SemanticRecordCapability,
    build_capability_graph,
)
from alertissimo.orchestration.ir import GetCrossmatchStep, Source, TargetSelector
from alertissimo.orchestration.planner import (
    EndpointPlan,
    PlanningDeferredError,
    UnsupportedStepError,
    plan_step,
)
from alertissimo.orchestration.validation import validate_step_capabilities


def _target(value: str) -> TargetSelector:
    return TargetSelector(ids=[value], kind="object")


def test_fink_ztf_catalog_qualified_target_selects_object_lookup():
    graph = build_capability_graph()
    step = GetCrossmatchStep(
        target=_target("ZTF18abbuksn"),
        catalog="panstarrs",
        sources=[Source(broker="fink", origin="ztf")],
    )

    result = validate_step_capabilities(step, graph)

    assert result.status == "supported"
    assert {item.endpoint for item in result.candidates} == {"objects"}
    assert plan_step(step, graph) == (
        EndpointPlan(broker="fink", origin="ztf", endpoint="objects"),
    )


def test_fink_lsst_catalog_qualified_target_selects_sources_lookup():
    graph = build_capability_graph()
    step = GetCrossmatchStep(
        target=_target("170587117485817955"),
        catalog="gaia",
        sources=[Source(broker="fink", origin="lsst")],
    )

    result = validate_step_capabilities(step, graph)

    assert result.status == "supported"
    assert {item.endpoint for item in result.candidates} == {"sources"}
    assert plan_step(step, graph) == (
        EndpointPlan(broker="fink", origin="lsst", endpoint="sources"),
    )


@pytest.mark.parametrize(
    ("origin", "object_id", "endpoint"),
    [
        ("ztf", "ZTF20aafqubg", "get_by_ztf_object_id"),
        ("lsst", "170587117485817955", "get_by_lsst_dia_object_id"),
    ],
)
def test_antares_catalog_crossmatch_uses_survey_object_binding(
    origin, object_id, endpoint
):
    graph = build_capability_graph()
    step = GetCrossmatchStep(
        target=_target(object_id),
        catalog="gaia",
        sources=[Source(broker="antares", origin=origin)],
    )

    result = validate_step_capabilities(step, graph)

    assert result.status == "supported"
    assert {item.endpoint for item in result.candidates} == {endpoint}
    assert plan_step(step, graph) == (
        EndpointPlan(broker="antares", origin=origin, endpoint=endpoint),
    )

    capability = result.candidates[0]
    assert capability.binding_roles == ("target_id",)
    assert capability.collection_binding_roles == ()


def test_dynamic_lasair_catalog_mapping_is_deferred_not_wildcard_proof():
    graph = build_capability_graph()
    step = GetCrossmatchStep(
        target=_target("ZTF18abbuksn"),
        catalog="gaia",
        sources=[Source(broker="lasair", origin="ztf")],
    )

    result = validate_step_capabilities(step, graph)

    assert result.status == "deferred"
    assert result.candidates == ()
    assert "dynamic producer" in result.source_results[0].reason
    with pytest.raises(PlanningDeferredError, match="deferred proof"):
        plan_step(step, graph)


def test_unregistered_catalog_is_unsupported_even_when_endpoint_has_crossmatches():
    graph = build_capability_graph()
    step = GetCrossmatchStep(
        target=_target("ZTF18abbuksn"),
        catalog="erosita",
        sources=[Source(broker="fink", origin="ztf")],
    )

    result = validate_step_capabilities(step, graph)

    assert result.status == "unsupported"
    assert result.candidates == ()
    assert "erosita" in result.source_results[0].reason
    with pytest.raises(UnsupportedStepError, match="erosita"):
        plan_step(step, graph)


def test_generic_conesearch_radius_is_not_crossmatch_radius_proof():
    graph = build_capability_graph()
    step = GetCrossmatchStep(
        target=_target("ZTF18abbuksn"),
        catalog="simbad",
        radius=2.0,
        sources=[Source(broker="fink", origin="ztf")],
    )

    result = validate_step_capabilities(step, graph)

    assert result.status == "unsupported"
    assert result.candidates == ()
    assert "requested radius" in result.source_results[0].reason


def test_explicit_crossmatch_target_requires_declared_target_binding():
    endpoint = EndpointCapability(
        "test",
        "ztf",
        "context",
        "/context",
        "GET",
        ("context_lookup",),
        (),
        (),
        None,
        False,
        "object",
    )
    record = SemanticRecordCapability(
        "test", "ztf", "crossmatch@gaia:test", ("context",), ()
    )
    graph = CapabilityGraph((endpoint,), (), (), (), (record,))
    step = GetCrossmatchStep(
        target=_target("A"),
        catalog="gaia",
        sources=[Source(broker="test", origin="ztf")],
    )

    result = validate_step_capabilities(step, graph)

    assert result.status == "unsupported"
    assert "target cannot be bound" in result.source_results[0].reason


def test_dedicated_crossmatch_radius_capability_is_accepted_when_semantically_mapped():
    endpoint = EndpointCapability(
        "test",
        "ztf",
        "catalog_crossmatch",
        "/crossmatch",
        "GET",
        ("catalog_crossmatch",),
        ("radius", "object_id"),
        ("radius", "object_id"),
        None,
        False,
        "object",
        ("target_id",),
        (),
    )
    record = SemanticRecordCapability(
        "test", "ztf", "crossmatch@gaia:test", (endpoint.endpoint,), ()
    )
    graph = CapabilityGraph((endpoint,), (), (), (), (record,))
    step = GetCrossmatchStep(
        target=_target("A"),
        catalog="gaia",
        radius=1.5,
        sources=[Source(broker="test", origin="ztf")],
    )

    result = validate_step_capabilities(step, graph)

    assert result.status == "supported"
    assert result.candidates == (endpoint,)
