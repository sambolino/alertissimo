from pathlib import Path

import pytest

from alertissimo.data_layer.execution.registry import EndpointRegistry
from alertissimo.orchestration.binding import (
    MissingBoundParameterError,
    ParameterBindingError,
    UnsupportedParameterBindingError,
    bind_endpoint,
    bind_workflow_run,
)
from alertissimo.orchestration.ir import (
    ConeSearchStep,
    GetForcedPhotometryStep,
    GetLightcurveStep,
    SqlQueryStep,
    WorkflowIR,
)
from alertissimo.orchestration.runtime import (
    EndpointPlan,
    StepRun,
    StepRunState,
    WorkflowRun,
)


def plan(broker: str, origin: str, endpoint: str) -> EndpointPlan:
    return EndpointPlan(broker=broker, origin=origin, endpoint=endpoint)


def test_alerce_lsst_lightcurve_uses_registry_target_binding():
    call = bind_endpoint(
        GetLightcurveStep(target_id="170587117485817955"),
        plan("alerce", "lsst", "query_lightcurve"),
        EndpointRegistry(),
    )

    assert call.params == {"oid": 170587117485817955}
    assert call.endpoint_spec.params["oid"]["bind"] == "target_id"
    assert call.endpoint_spec.fixed_params == {"survey": "lsst"}
    assert "format" not in call.params  # Executor retains default ownership.
    assert "survey" not in call.params  # Executor retains fixed-param ownership.


def test_lasair_ztf_lightcurve_uses_declared_csv_collection():
    call = bind_endpoint(
        GetLightcurveStep(target_id="ZTF20abc"),
        plan("lasair", "ztf", "lightcurves"),
        EndpointRegistry(),
    )

    assert call.params == {"objectIds": "ZTF20abc"}
    assert call.endpoint_spec.params["objectIds"]["binding"] == {
        "collection": "csv",
        "max_items": 50,
    }


def test_alerce_forced_photometry_target_binding():
    call = bind_endpoint(
        GetForcedPhotometryStep(target_id="123"),
        plan("alerce", "lsst", "query_forced_photometry"),
        EndpointRegistry(),
    )
    assert call.params == {"oid": 123}


def test_registry_physical_types_distinguish_identical_target_role():
    registry = EndpointRegistry()

    alerce_call = bind_endpoint(
        GetLightcurveStep(target_id="170587117485817955"),
        plan("alerce", "lsst", "query_lightcurve"),
        registry,
    )
    lasair_call = bind_endpoint(
        GetLightcurveStep(target_id="ZTF20abc"),
        plan("lasair", "ztf", "lightcurves"),
        registry,
    )

    assert alerce_call.params == {"oid": 170587117485817955}
    assert lasair_call.params == {"objectIds": "ZTF20abc"}


def test_invalid_integer_target_fails_during_binding():
    with pytest.raises(ParameterBindingError) as error:
        bind_endpoint(
            GetLightcurveStep(target_id="not-an-integer"),
            plan("alerce", "lsst", "query_lightcurve"),
            EndpointRegistry(),
        )

    message = str(error.value)
    assert "alerce/lsst/query_lightcurve" in message
    assert "'oid'" in message
    assert "'integer'" in message
    assert "'target_id'" in message
    assert "'not-an-integer'" in message


def test_cone_binding_passes_arcsecond_contract_through():
    call = bind_endpoint(
        ConeSearchStep(semantic_type="summary", ra=12.5, dec=-4, radius=3),
        plan("lasair", "ztf", "cone"),
        EndpointRegistry(),
    )

    assert call.params == {"ra": 12.5, "dec": -4.0, "radius": 3.0}
    assert call.endpoint_spec.params["radius"]["unit"] == "arcsec"
    # The required requestType is resolved by its endpoint default, not fabricated.
    assert "requestType" not in call.params


def test_repeated_steps_keep_distinct_occurrence_bindings():
    workflow = WorkflowIR(
        steps=[GetLightcurveStep(target_id="A"), GetLightcurveStep(target_id="B")]
    )
    endpoint = plan("lasair", "ztf", "lightcurves")
    run = WorkflowRun(
        workflow=workflow,
        steps=(
            StepRun(step_index=0, state=StepRunState.PLANNED, endpoint_plans=(endpoint,)),
            StepRun(step_index=1, state=StepRunState.PLANNED, endpoint_plans=(endpoint,)),
        ),
    )

    results = bind_workflow_run(run, EndpointRegistry())

    assert [result.step_index for result in results] == [0, 1]
    assert [result.bound_calls[0].params["objectIds"] for result in results] == [
        "A",
        "B",
    ]
    assert all(step.state == StepRunState.PLANNED for step in run.steps)


def test_pending_workflow_run_cannot_be_bound():
    workflow = WorkflowIR(steps=[GetLightcurveStep(target_id="ZTF20abc")])
    run = WorkflowRun.from_workflow(workflow)

    with pytest.raises(
        ParameterBindingError,
        match="step_index 0 is pending; binding requires planned state",
    ):
        bind_workflow_run(run, EndpointRegistry())

    assert run.steps[0].state == StepRunState.PENDING


def test_missing_required_parameter_reports_full_endpoint_context():
    with pytest.raises(MissingBoundParameterError) as error:
        bind_endpoint(
            GetLightcurveStep(),
            plan("alerce", "lsst", "query_lightcurve"),
            EndpointRegistry(),
        )

    message = str(error.value)
    assert "alerce/lsst/query_lightcurve" in message
    assert "'oid'" in message
    assert "'target_id'" in message


def test_optional_canonical_fields_are_not_fabricated():
    call = bind_endpoint(
        GetLightcurveStep(target_id="A", bands=None, time_context=None),
        plan("lasair", "ztf", "lightcurves"),
        EndpointRegistry(),
    )
    assert call.params == {"objectIds": "A"}


def test_sql_split_contract_is_explicitly_deferred():
    with pytest.raises(UnsupportedParameterBindingError, match="canonical query"):
        bind_endpoint(
            SqlQueryStep(semantic_type="summary", query="SELECT objectId FROM objects"),
            plan("lasair", "ztf", "query"),
            EndpointRegistry(),
        )


def test_production_binder_has_no_provider_dispatch_or_physical_names():
    source = (
        Path(__file__).parents[1]
        / "alertissimo"
        / "orchestration"
        / "binding"
        / "binder.py"
    ).read_text(encoding="utf-8").lower()
    for provider_or_physical_name in (
        "alerce",
        "lasair",
        "fink",
        "antares",
        '"oid"',
        '"objectid"',
        '"objectids"',
    ):
        assert provider_or_physical_name not in source


def test_plural_targets_bind_once_and_preserve_order():
    registry = EndpointRegistry()
    cases = [
        ("fink", "lsst", "sources", "diaObjectId"),
        ("fink", "lsst", "fp", "diaObjectId"),
        ("fink", "ztf", "objects", "objectId"),
        ("lasair", "ztf", "lightcurves", "objectIds"),
    ]
    for broker, origin, endpoint, physical in cases:
        call = bind_endpoint(
            GetLightcurveStep(target_ids=["A", "B"]),
            plan(broker, origin, endpoint), registry,
        )
        assert call.params == {physical: "A,B"}


def test_singular_binding_unwraps_one_and_rejects_many():
    registry = EndpointRegistry()
    endpoint = plan("alerce", "lsst", "query_lightcurve")
    assert bind_endpoint(GetLightcurveStep(target_ids=["123"]), endpoint, registry).params == {"oid": 123}
    with pytest.raises(UnsupportedParameterBindingError) as error:
        bind_endpoint(GetLightcurveStep(target_ids=["1", "2"]), endpoint, registry)
    assert "alerce/lsst/query_lightcurve" in str(error.value)
    assert "target_id" in str(error.value)
    assert "cardinality 2" in str(error.value)


def test_collection_limit_is_enforced_before_execution():
    endpoint = plan("lasair", "ztf", "lightcurves")
    registry = EndpointRegistry()
    assert bind_endpoint(GetLightcurveStep(target_ids=[str(i) for i in range(50)]), endpoint, registry)
    with pytest.raises(UnsupportedParameterBindingError, match="declared limit 50"):
        bind_endpoint(GetLightcurveStep(target_ids=[str(i) for i in range(51)]), endpoint, registry)
