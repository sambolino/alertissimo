from alertissimo.orchestration.ir import TargetSelector

from pathlib import Path

import pytest

from alertissimo.data_layer.execution.registry import EndpointRegistry
from alertissimo.orchestration.binding import (
    MissingBoundParameterError,
    ParameterBindingError,
    UnsupportedParameterBindingError,
    bind_endpoint,
    bind_endpoint_calls,
    bind_workflow_run,
)
from alertissimo.orchestration.ir import (
    ConeSearchStep,
    GetClassificationStep,
    GetCrossmatchStep,
    GetForcedPhotometryStep,
    GetLightcurveStep,
    LookupStep,
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
        GetLightcurveStep(target=TargetSelector(ids=["170587117485817955"], kind="object")),
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
        GetLightcurveStep(target=TargetSelector(ids=["ZTF20abc"], kind="object")),
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
        GetForcedPhotometryStep(target=TargetSelector(ids=["123"], kind="object")),
        plan("alerce", "lsst", "query_forced_photometry"),
        EndpointRegistry(),
    )
    assert call.params == {"oid": 123}


def test_registry_physical_types_distinguish_identical_target_role():
    registry = EndpointRegistry()

    alerce_call = bind_endpoint(
        GetLightcurveStep(target=TargetSelector(ids=["170587117485817955"], kind="object")),
        plan("alerce", "lsst", "query_lightcurve"),
        registry,
    )
    lasair_call = bind_endpoint(
        GetLightcurveStep(target=TargetSelector(ids=["ZTF20abc"], kind="object")),
        plan("lasair", "ztf", "lightcurves"),
        registry,
    )

    assert alerce_call.params == {"oid": 170587117485817955}
    assert lasair_call.params == {"objectIds": "ZTF20abc"}


def test_invalid_integer_target_fails_during_binding():
    with pytest.raises(ParameterBindingError) as error:
        bind_endpoint(
            GetLightcurveStep(target=TargetSelector(ids=["not-an-integer"], kind="object")),
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
        steps=[GetLightcurveStep(target=TargetSelector(ids=["A"], kind="object")), GetLightcurveStep(target=TargetSelector(ids=["B"], kind="object"))]
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
    workflow = WorkflowIR(steps=[GetLightcurveStep(target=TargetSelector(ids=["ZTF20abc"], kind="object"))])
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
        GetLightcurveStep(target=TargetSelector(ids=["A"], kind="object"), bands=None, time_context=None),
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
            GetLightcurveStep(target=TargetSelector(ids=["A", "B"], kind="object")),
            plan(broker, origin, endpoint), registry,
        )
        assert call.params == {physical: "A,B"}


def test_singular_binding_unwraps_one_and_rejects_many():
    registry = EndpointRegistry()
    endpoint = plan("alerce", "lsst", "query_lightcurve")
    assert bind_endpoint(GetLightcurveStep(target=TargetSelector(ids=["123"], kind="object")), endpoint, registry).params == {"oid": 123}
    with pytest.raises(UnsupportedParameterBindingError) as error:
        bind_endpoint(GetLightcurveStep(target=TargetSelector(ids=["1", "2"], kind="object")), endpoint, registry)
    assert "alerce/lsst/query_lightcurve" in str(error.value)
    assert "target_id" in str(error.value)
    assert "cardinality 2" in str(error.value)


def test_lasair_sherlock_physical_bindings_are_registry_driven():
    registry = EndpointRegistry()
    ztf_scalar = bind_endpoint(
        GetClassificationStep(target=TargetSelector(ids=["ZTF-A"], kind="object")),
        plan("lasair", "ztf", "sherlock_object"), registry,
    )
    ztf_batch = bind_endpoint(
        GetCrossmatchStep(target=TargetSelector(ids=["ZTF-A", "ZTF-B"], kind="object")),
        plan("lasair", "ztf", "sherlock_objects"), registry,
    )
    lsst_scalar = bind_endpoint(
        GetClassificationStep(target=TargetSelector(ids=["123"], kind="object")),
        plan("lasair", "lsst", "sherlock_object"), registry,
    )
    lsst_batch = bind_endpoint(
        GetCrossmatchStep(target=TargetSelector(ids=["123", "456"], kind="object")),
        plan("lasair", "lsst", "sherlock_object"), registry,
    )

    assert ztf_scalar.params == {"objectId": "ZTF-A"}
    assert ztf_batch.params == {"objectIds": "ZTF-A,ZTF-B"}
    assert lsst_scalar.params == {"objectId": "123"}
    assert lsst_batch.params == {"objectId": "123,456"}
    assert lsst_batch.endpoint_plan.endpoint == "sherlock_object"


def test_collection_limit_is_enforced_before_execution():
    endpoint = plan("lasair", "ztf", "lightcurves")
    registry = EndpointRegistry()
    assert bind_endpoint(GetLightcurveStep(target=TargetSelector(ids=[str(i) for i in range(50)], kind="object")), endpoint, registry)
    with pytest.raises(UnsupportedParameterBindingError, match="declared limit 50"):
        bind_endpoint(GetLightcurveStep(target=TargetSelector(ids=[str(i) for i in range(51)], kind="object")), endpoint, registry)


def test_generic_binding_fans_plural_lookup_out_over_singular_endpoint():
    calls = bind_endpoint_calls(
        LookupStep(
            target=TargetSelector(ids=["ZTF-A", "ZTF-B"], kind="object"),
        ),
        plan("antares", "ztf", "get_by_ztf_object_id"),
        EndpointRegistry(),
    )

    assert [call.params for call in calls] == [
        {"ztf_object_id": "ZTF-A"},
        {"ztf_object_id": "ZTF-B"},
    ]


def test_generic_binding_keeps_plural_lookup_as_one_collection_call():
    calls = bind_endpoint_calls(
        LookupStep(
            target=TargetSelector(ids=["ZTF-A", "ZTF-B"], kind="object"),
        ),
        plan("lasair", "ztf", "objects"),
        EndpointRegistry(),
    )

    assert [call.params for call in calls] == [{"objectIds": "ZTF-A,ZTF-B"}]


def test_generic_binding_chunks_collection_calls_at_declared_limit():
    ids = [f"ZTF-{index}" for index in range(51)]
    calls = bind_endpoint_calls(
        GetLightcurveStep(target=TargetSelector(ids=ids, kind="object")),
        plan("lasair", "ztf", "lightcurves"),
        EndpointRegistry(),
    )

    assert len(calls) == 2
    assert calls[0].params == {"objectIds": ",".join(ids[:50])}
    assert calls[1].params == {"objectIds": ids[50]}


def test_workflow_binding_aligns_singular_lookup_fanout_to_one_plan():
    workflow = WorkflowIR(
        steps=[
            LookupStep(
                target=TargetSelector(ids=["ZTF-A", "ZTF-B"], kind="object"),
            )
        ]
    )
    endpoint = plan("antares", "ztf", "get_by_ztf_object_id")
    run = WorkflowRun(
        workflow=workflow,
        steps=(
            StepRun(
                step_index=0,
                state=StepRunState.PLANNED,
                endpoint_plans=(endpoint,),
            ),
        ),
    )

    binding = bind_workflow_run(run, EndpointRegistry())[0]

    assert [call.params for call in binding.bound_calls] == [
        {"ztf_object_id": "ZTF-A"},
        {"ztf_object_id": "ZTF-B"},
    ]
    assert binding.plan_indexes == (0, 0)


def test_multi_target_multiple_provider_binding_is_one_result_with_two_calls():
    from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
    from alertissimo.orchestration.ir import Source
    from alertissimo.orchestration.planner import plan_workflow

    workflow = WorkflowIR(steps=[GetLightcurveStep(
        target=TargetSelector(ids=["A", "B"], kind="object"),
        sources=[Source(broker="fink", origin="ztf"), Source(broker="lasair", origin="ztf")],
    )])
    results = bind_workflow_run(plan_workflow(workflow, build_capability_graph()), EndpointRegistry())

    assert len(results) == 1
    assert [(call.endpoint_plan.broker, call.params) for call in results[0].bound_calls] == [
        ("fink", {"objectId": "A,B"}),
        ("lasair", {"objectIds": "A,B"}),
    ]
