"""Offline endpoint-selection tests for orchestration planner v1."""

import pytest

from alertissimo.data_layer.execution.registry import EndpointRegistry
from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraph, EndpointCapability, SemanticRecordCapability, build_capability_graph,
)
from alertissimo.orchestration.ir.models import (
    ClassifyStep,
    ConeSearchStep,
    FilterStep,
    GetClassificationStep,
    GetCutoutStep,
    GetCrossmatchStep,
    GetDataProductStep,
    GetForcedPhotometryStep,
    GetLightcurveStep,
    GetSpectrumStep,
    LightcurveStep,
    LookupStep,
    MatchStep,
    Source,
    SqlQueryStep,
    WorkflowIR,
)
from alertissimo.orchestration.planner import (
    EndpointPlan,
    PlanningAmbiguityError,
    PlanningDeferredError,
    PlanningNotApplicableError,
    UnsupportedStepError,
    plan_step,
    plan_workflow,
)
from alertissimo.orchestration.runtime import StepRunState
from alertissimo.orchestration.validation import validate_step_capabilities


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def _assert_resolves(plans):
    registry = EndpointRegistry()
    for plan in plans:
        spec = registry.resolve(plan.broker, plan.origin, plan.endpoint)
        assert (spec.broker, spec.origin, spec.endpoint) == (
            plan.broker,
            plan.origin,
            plan.endpoint,
        )


def test_explicit_lasair_ztf_lightcurve_selects_registered_endpoint(graph):
    step = GetLightcurveStep(
        target_id="ZTF20abc", sources=[Source(broker="lasair", origin="ztf")]
    )
    plans = plan_step(step, graph)
    assert plans == (
        EndpointPlan(broker="lasair", origin="ztf", endpoint="lightcurves"),
    )
    _assert_resolves(plans)


def test_explicit_alerce_lsst_forced_photometry(graph):
    plans = plan_step(
        GetForcedPhotometryStep(sources=[Source(broker="alerce", origin="lsst")]), graph
    )
    assert [(p.broker, p.origin, p.endpoint) for p in plans] == [
        ("alerce", "lsst", "query_forced_photometry")
    ]
    _assert_resolves(plans)


def test_explicit_cone_and_sql_select_only_matching_operations(graph):
    cone = plan_step(
        ConeSearchStep(
            semantic_type="summary",
            ra=12,
            dec=-3,
            radius=0.1,
            sources=[Source(broker="lasair", origin="ztf")],
        ),
        graph,
    )
    sql = plan_step(
        SqlQueryStep(
            semantic_type="summary",
            query="select * from objects",
            sources=[Source(broker="lasair", origin="ztf")],
        ),
        graph,
    )
    assert cone[0].endpoint == "cone"
    assert sql[0].endpoint == "query"
    for plan, operation in ((cone[0], "cone_search"), (sql[0], "sql_query")):
        capability = next(
            item
            for item in graph.endpoint_capabilities
            if (item.broker, item.origin, item.endpoint)
            == (plan.broker, plan.origin, plan.endpoint)
        )
        assert operation in capability.operation_types
    _assert_resolves(cone + sql)


def test_classification_uses_semantic_candidates_without_guessing(graph):
    step = GetClassificationStep(sources=[Source(broker="alerce", origin="lsst")])
    candidates = validate_step_capabilities(step, graph).candidates
    if len(candidates) == 1:
        plans = plan_step(step, graph)
        assert plans[0].endpoint == candidates[0].endpoint
        _assert_resolves(plans)
    else:
        with pytest.raises(PlanningAmbiguityError):
            plan_step(step, graph)


def test_multiple_explicit_sources_each_select_one_endpoint(graph):
    unconstrained = validate_step_capabilities(GetLightcurveStep(), graph).candidates
    by_source = {}
    for item in unconstrained:
        by_source.setdefault((item.broker, item.origin), []).append(item)
    unique_sources = [
        key for key, values in sorted(by_source.items()) if len(values) == 1
    ]
    assert len(unique_sources) >= 2
    sources = [
        Source(broker=broker, origin=origin) for broker, origin in unique_sources[:2]
    ]
    plans = plan_step(GetLightcurveStep(sources=sources), graph)
    assert [(p.broker, p.origin) for p in plans] == unique_sources[:2]
    _assert_resolves(plans)

    run = plan_workflow(WorkflowIR(steps=[GetLightcurveStep(sources=sources)]), graph)
    assert len(run.steps) == 1
    assert run.steps[0].endpoint_plans == plans


def test_unconstrained_multiple_candidates_are_ambiguous_and_deterministic(graph):
    step = GetLightcurveStep()
    with pytest.raises(PlanningAmbiguityError) as first:
        plan_step(step, graph)
    with pytest.raises(PlanningAmbiguityError) as second:
        plan_step(step, graph)
    assert str(first.value) == str(second.value)
    assert "/" in str(first.value)


def test_unsupported_deferred_and_local_statuses_are_distinct(graph):
    with pytest.raises(UnsupportedStepError, match="get_spectrum"):
        plan_step(GetSpectrumStep(), graph)
    with pytest.raises(PlanningDeferredError, match="identifier"):
        plan_step(LookupStep(id="ZTF20abc"), graph)
    for step in (
        ClassifyStep(),
        FilterStep(criteria={}),
        MatchStep(),
        LightcurveStep(),
    ):
        with pytest.raises(PlanningNotApplicableError):
            plan_step(step, graph)


def test_workflow_planning_preserves_step_boundaries_and_fails_on_local_steps(graph):
    workflow = WorkflowIR(
        steps=[
            SqlQueryStep(
                semantic_type="summary",
                query="select 1",
                sources=[Source(broker="lasair", origin="ztf")],
            ),
            GetLightcurveStep(
                target_id="ZTF20abc",
                sources=[Source(broker="lasair", origin="ztf")],
            ),
        ]
    )
    run = plan_workflow(workflow, graph)
    assert [step.state for step in run.steps] == [
        StepRunState.PLANNED,
        StepRunState.PLANNED,
    ]
    assert [[item.endpoint for item in step.endpoint_plans] for step in run.steps] == [
        ["query"],
        ["lightcurves"],
    ]
    _assert_resolves(
        tuple(plan for step_run in run.steps for plan in step_run.endpoint_plans)
    )
    with pytest.raises(PlanningNotApplicableError):
        plan_workflow(WorkflowIR(steps=[FilterStep(criteria={})]), graph)


def test_multi_target_planning_uses_collection_capable_endpoints(graph):
    cases = [
        (GetLightcurveStep, "fink", "lsst", "sources"),
        (GetForcedPhotometryStep, "fink", "lsst", "fp"),
        (GetLightcurveStep, "fink", "ztf", "objects"),
        (GetLightcurveStep, "lasair", "ztf", "lightcurves"),
    ]
    for step_type, broker, origin, endpoint in cases:
        plans = plan_step(step_type(target_ids=["A", "B"], sources=[Source(broker=broker, origin=origin)]), graph)
        assert len(plans) == 1
        assert plans[0].endpoint == endpoint

    with pytest.raises(UnsupportedStepError, match="multi-target binding"):
        plan_step(GetLightcurveStep(target_ids=["1", "2"], sources=[Source(broker="alerce", origin="lsst")]), graph)


def test_multi_target_multiple_sources_remain_one_plan_each(graph):
    step = GetLightcurveStep(
        target_ids=["A", "B"],
        sources=[Source(broker="fink", origin="ztf"), Source(broker="lasair", origin="ztf")],
    )
    plans = plan_step(step, graph)
    assert [(p.broker, p.endpoint) for p in plans] == [("fink", "objects"), ("lasair", "lightcurves")]


def test_singular_cutout_accepts_one_collection_item_but_rejects_many(graph):
    source = [Source(broker="fink", origin="ztf")]
    assert plan_step(GetCutoutStep(target_ids=["A"], sources=source), graph)[0].endpoint == "cutouts"
    with pytest.raises(UnsupportedStepError, match="multi-target binding"):
        plan_step(GetCutoutStep(target_ids=["A", "B"], sources=source), graph)


def test_singular_data_product_is_not_planned_for_multiple_targets():
    capability = EndpointCapability(
        "test", "ztf", "product", "/product", "GET",
        ("data_product_lookup",), (), (), None, False, "object",
        ("target_id",), (),
    )
    graph = CapabilityGraph((capability,), (), (), (), ())
    step = GetDataProductStep(target_ids=["A", "B"], sources=[Source(broker="test")])
    assert validate_step_capabilities(step, graph).status == "unsupported"
    with pytest.raises(UnsupportedStepError, match="multi-target binding"):
        plan_step(step, graph)


def test_multi_target_spectrum_planning_reports_missing_capability(graph):
    with pytest.raises(UnsupportedStepError) as caught:
        plan_step(GetSpectrumStep(target_ids=["A", "B"]), graph)
    assert "no compatible registered endpoint capability found" in str(caught.value)
    assert "multi-target binding" not in str(caught.value)


@pytest.mark.parametrize(("step_type", "noun"), [
    (GetClassificationStep, "classification"),
    (GetCrossmatchStep, "crossmatch"),
])
def test_semantic_target_planning_uses_only_collection_candidate(step_type, noun):
    singular = EndpointCapability(
        "test", "ztf", f"{noun}_one", "/one", "GET",
        ("context_lookup",), (), (), None, False, "object",
        ("target_id",), (),
    )
    collection = EndpointCapability(
        "test", "ztf", f"{noun}_many", "/many", "GET",
        ("context_lookup",), (), (), None, False, "array",
        ("target_id",), ("target_id",),
    )
    records = (SemanticRecordCapability(
        "test", "ztf", noun, (singular.endpoint, collection.endpoint), (),
    ),)
    graph = CapabilityGraph((singular, collection), (), (), (), records)
    source = [Source(broker="test", origin="ztf")]
    with pytest.raises(PlanningAmbiguityError):
        plan_step(step_type(target_id="A", sources=source), graph)
    assert plan_step(step_type(target_ids=["A", "B"], sources=source), graph)[0].endpoint == f"{noun}_many"


@pytest.mark.parametrize("step_type", [GetClassificationStep, GetCrossmatchStep])
def test_lasair_sherlock_planning_preserves_real_ambiguity(step_type, graph):
    ztf = step_type(
        target_ids=["A", "B"],
        sources=[Source(broker="lasair", origin="ztf")],
    )
    candidates = validate_step_capabilities(ztf, graph).candidates
    assert {"objects", "sherlock_objects"} <= {item.endpoint for item in candidates}
    assert "sherlock_object" not in {item.endpoint for item in candidates}
    with pytest.raises(PlanningAmbiguityError):
        plan_step(ztf, graph)

    lsst = step_type(
        target_ids=["313761042336317573", "313761042336317574"],
        sources=[Source(broker="lasair", origin="lsst")],
    )
    assert plan_step(lsst, graph) == (
        EndpointPlan(broker="lasair", origin="lsst", endpoint="sherlock_object"),
    )
