"""Contracts for semantic cone coordinates binding into provider endpoints."""

import pytest

from alertissimo.data_layer.execution import EndpointRegistry
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.orchestration.binding import bind_endpoint
from alertissimo.orchestration.ir import ConeSearchStep, Source, WorkflowIR
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import EndpointPlan


RA = 124.87996115142856
DEC = -6.0205001
RADIUS_ARCSEC = 300.0


SCALAR_POSITION_ENDPOINTS = (
    ("fink", "lsst", "conesearch"),
    ("fink", "ztf", "conesearch"),
    ("alerce", "lsst", "query_objects"),
    ("alerce", "ztf", "query_objects"),
    ("lasair", "lsst", "cone"),
    ("lasair", "ztf", "cone"),
    # catsHTM is not the primary object cone-search operation, but it exposes the
    # same scalar coordinate contract and should remain declaratively bindable.
    ("alerce", "lsst", "catshtm_conesearch"),
    ("alerce", "ztf", "catshtm_conesearch"),
)


@pytest.mark.parametrize(("broker", "origin", "endpoint"), SCALAR_POSITION_ENDPOINTS)
def test_scalar_position_endpoints_declare_and_apply_canonical_coordinate_bindings(
    broker, origin, endpoint
):
    registry = EndpointRegistry()
    spec = registry.resolve(broker, origin, endpoint)

    assert spec.params["ra"]["bind"] == "ra"
    assert spec.params["dec"]["bind"] == "dec"
    assert spec.params["radius"]["bind"] == "radius"

    step = ConeSearchStep(
        semantic_type="summary",
        ra=RA,
        dec=DEC,
        radius=RADIUS_ARCSEC,
        sources=[Source(broker=broker, origin=origin)],
    )
    call = bind_endpoint(
        step,
        EndpointPlan(
            broker=broker,
            origin=origin,
            endpoint=endpoint,
            semantic_type="summary",
        ),
        registry,
    )

    assert call.params["ra"] == RA
    assert call.params["dec"] == DEC
    assert call.params["radius"] == RADIUS_ARCSEC


def test_fink_multisurvey_cone_plan_binds_same_semantic_coordinates_per_origin():
    graph = build_capability_graph()
    registry = EndpointRegistry()
    workflow = WorkflowIR(
        steps=[
            ConeSearchStep(
                semantic_type="summary",
                ra=RA,
                dec=DEC,
                radius=RADIUS_ARCSEC,
                sources=[
                    Source(broker="fink", origin="lsst"),
                    Source(broker="fink", origin="ztf"),
                ],
            )
        ]
    )

    run = plan_workflow(workflow, graph)
    step_run = run.steps[0]
    assert [
        (plan.broker, plan.origin, plan.endpoint)
        for plan in step_run.endpoint_plans
    ] == [
        ("fink", "lsst", "conesearch"),
        ("fink", "ztf", "conesearch"),
    ]

    calls = tuple(
        bind_endpoint(workflow.steps[0], plan, registry)
        for plan in step_run.endpoint_plans
    )
    assert [call.params for call in calls] == [
        {"ra": RA, "dec": DEC, "radius": RADIUS_ARCSEC},
        {"ra": RA, "dec": DEC, "radius": RADIUS_ARCSEC},
    ]


def test_antares_cone_contract_keeps_native_types_with_declarative_adapters():
    """ANTARES stays physically SkyCoord/Angle while canonical roles remain explicit."""

    registry = EndpointRegistry()
    for origin in ("lsst", "ztf"):
        spec = registry.resolve("antares", origin, "cone_search")
        assert "ra" not in spec.params
        assert "dec" not in spec.params

        center = spec.params["center"]
        assert center["type"] == "SkyCoord"
        assert "bind" not in center
        assert center["binding"] == {
            "roles": ["ra", "dec"],
            "adapter": "alertissimo.data_layer.providers.antares_binding:skycoord_icrs_degrees",
        }

        radius = spec.params["radius"]
        assert radius["type"] == "Angle"
        assert radius["bind"] == "radius"
        assert radius["binding"] == {
            "adapter": "alertissimo.data_layer.providers.antares_binding:angle_arcsec",
        }
