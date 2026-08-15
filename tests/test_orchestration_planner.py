"""Offline tests for deterministic provider endpoint selection."""

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


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


@pytest.mark.parametrize(
    ("step", "identity"),
    [
        (
            GetLightcurveStep(
                target_id="ZTF20abc",
                sources=[Source(broker="lasair", origin="ztf")],
            ),
            ("lasair", "ztf", "lightcurves"),
        ),
        (
            GetForcedPhotometryStep(sources=[Source(broker="alerce", origin="lsst")]),
            ("alerce", "lsst", "query_forced_photometry"),
        ),
        (
            ConeSearchStep(
                semantic_type="summary",
                ra=1,
                dec=2,
                radius=3,
                sources=[Source(broker="lasair", origin="ztf")],
            ),
            ("lasair", "ztf", "cone"),
        ),
        (
            SqlQueryStep(
                semantic_type="summary",
                query="SELECT objectId",
                sources=[Source(broker="lasair", origin="ztf")],
            ),
            ("lasair", "ztf", "query"),
        ),
        (
            GetClassificationStep(sources=[Source(broker="alerce", origin="lsst")]),
            ("alerce", "lsst", "query_probabilities"),
        ),
    ],
)
def test_real_explicit_source_endpoint_selection_and_resolution(graph, step, identity):
    plans = plan_step(step, graph)
    assert len(plans) == 1
    plan = plans[0]
    assert (plan.broker, plan.origin, plan.endpoint) == identity
    spec = EndpointRegistry().resolve(plan.broker, plan.origin, plan.endpoint)
    assert (spec.broker, spec.origin, spec.endpoint) == identity


def test_multiple_explicit_sources_each_produce_a_plan(graph):
    step = GetLightcurveStep(
        sources=[
            Source(broker="lasair", origin="ztf"),
            Source(broker="alerce", origin="ztf"),
        ]
    )
    assert plan_step(step, graph) == (
        EndpointPlan("get_lightcurve", "lasair", "ztf", "lightcurves"),
        EndpointPlan("get_lightcurve", "alerce", "ztf", "query_lightcurve"),
    )


def test_unconstrained_multi_candidate_selection_is_ambiguous_and_deterministic(graph):
    step = GetLightcurveStep()
    with pytest.raises(PlanningAmbiguityError) as first:
        plan_step(step, graph)
    with pytest.raises(PlanningAmbiguityError) as second:
        plan_step(step, graph)
    assert str(first.value) == str(second.value)
    assert "alerce/lsst/query_lightcurve" in str(first.value)
    assert "lasair/ztf/lightcurves" in str(first.value)


def test_unsupported_and_deferred_steps_remain_distinct(graph):
    with pytest.raises(UnsupportedStepError, match="get_spectrum"):
        plan_step(GetSpectrumStep(), graph)
    with pytest.raises(PlanningDeferredError, match="identifier"):
        plan_step(LookupStep(id="namespace-not-yet-known"), graph)


@pytest.mark.parametrize(
    "step",
    [ClassifyStep(), FilterStep(criteria={"x": 1}), MatchStep(), LightcurveStep()],
)
def test_local_steps_are_not_provider_planning_failures(graph, step):
    with pytest.raises(PlanningNotApplicableError, match="local/orchestration"):
        plan_step(step, graph)


def test_workflow_planning_preserves_step_and_source_order(graph):
    workflow = WorkflowIR(
        steps=[
            GetLightcurveStep(sources=[Source(broker="lasair", origin="ztf")]),
            SqlQueryStep(
                semantic_type="summary",
                query="SELECT objectId",
                sources=[Source(broker="lasair", origin="ztf")],
            ),
        ]
    )
    plan = plan_workflow(workflow, graph)
    assert [item.endpoint for item in plan.endpoint_plans] == ["lightcurves", "query"]


def test_workflow_fails_instead_of_omitting_local_steps(graph):
    workflow = WorkflowIR(
        steps=[
            GetLightcurveStep(sources=[Source(broker="lasair", origin="ztf")]),
            ClassifyStep(),
        ]
    )
    with pytest.raises(PlanningNotApplicableError):
        plan_workflow(workflow, graph)
