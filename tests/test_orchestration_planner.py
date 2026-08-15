"""Offline endpoint-selection tests for orchestration planner v1."""

import pytest

from alertissimo.data_layer.execution.registry import EndpointRegistry
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.orchestration.ir.models import (
    ClassifyStep,
    ConeSearchStep,
    FilterStep,
    GetClassificationStep,
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
