"""Focused tests for the provider-independent orchestration IR."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from alertissimo.orchestration.ir import (
    ActionStep, AggregateStep, AnalyzeStep, ClassifyStep, CompareStep,
    ConeSearchStep, ConfirmStep, ExportStep, FilterStep, FollowupRequestStep,
    GetClassificationStep, GetCrossmatchStep, GetCutoutStep, GetDataProductStep,
    GetForcedPhotometryStep, GetLightcurveStep, GetSpectrumStep, GetStep,
    LightcurveStep, LookupStep, MatchStep, MethodAnalysisStep, MonitorStep,
    NotifyStep, SearchStep, SemanticSearchStep, Source, SqlQueryStep, TimeContext,
    UtilityScoreStep, WorkflowIR,
)


def concrete_steps():
    """Return one valid instance of every concrete operation in the census."""
    source = Source(broker="fink", origin="ztf")
    time = TimeContext(start_time="2025-01-01T00:00:00Z", end_time="2025-01-02T00:00:00Z")
    return [
        LookupStep(id="ZTF-object-or-alert", sources=[source]),
        SemanticSearchStep(semantic_type="summary", criteria={"classification": "SN"}, time_context=time),
        ConeSearchStep(semantic_type="detection", ra=12.5, dec=-20, radius=0.1),
        SqlQueryStep(semantic_type="classification", query="SELECT class FROM classifications"),
        FilterStep(criteria={"magnitude": {"lt": 20}}),
        GetLightcurveStep(target_id="target", bands=["g", "r"], time_context=time),
        GetCrossmatchStep(target_id="target", catalog="gaia", radius=1.0),
        GetCutoutStep(target_id="target", format="fits", size=30),
        GetForcedPhotometryStep(target_id="target", bands=["g"], time_context=time),
        GetClassificationStep(target_id="target"),
        GetSpectrumStep(target_id="target", time_context=time),
        GetDataProductStep(target_id="target", product_type="image"),
        LightcurveStep(target_id="target", bands=["g", "r"], time_context=time),
        MatchStep(target_id="target", method="spatial", params={"radius": 1}),
        MethodAnalysisStep(target_id="target", method="periodicity", params={"period_min": 1}),
        ClassifyStep(target_id="target", method="random_forest"),
        AggregateStep(method="mean", field="photometry.flux", group_by=["band"]),
        CompareStep(target="classification", method="disagreement"),
        UtilityScoreStep(target_id="target", method="followup_priority"),
        ConfirmStep(target_id="target", required_agreement=1, sources=[source]),
        MonitorStep(stream="alerts", criteria={"survey": "ztf"}),
        FollowupRequestStep(request_type="spectroscopy", target_id="target", facility="generic"),
        NotifyStep(channel="email", recipient="team@example.test", message="Candidate found"),
        ExportStep(destination="portfolio.json", format="json"),
    ]


def test_constructs_every_concrete_step():
    steps = concrete_steps()
    assert len(steps) == 24
    assert len({step.op for step in steps}) == len(steps)


def test_hierarchies_express_operation_concepts():
    searches = [
        SemanticSearchStep(semantic_type="summary"),
        ConeSearchStep(semantic_type="detection", ra=1, dec=2, radius=0.1),
        SqlQueryStep(semantic_type="classification", query="SELECT class FROM records"),
    ]
    assert all(isinstance(step, SearchStep) for step in searches)
    assert not issubclass(FilterStep, SearchStep)

    get_types = (GetLightcurveStep, GetCrossmatchStep, GetCutoutStep,
                 GetForcedPhotometryStep, GetClassificationStep, GetSpectrumStep,
                 GetDataProductStep)
    assert all(issubclass(step_type, GetStep) for step_type in get_types)
    assert not isinstance(LightcurveStep(), GetLightcurveStep)
    assert not isinstance(MatchStep(), GetCrossmatchStep)
    assert not issubclass(MatchStep, CompareStep)

    analysis_types = (MethodAnalysisStep, ClassifyStep, AggregateStep,
                      CompareStep, UtilityScoreStep)
    assert all(issubclass(step_type, AnalyzeStep) for step_type in analysis_types)
    assert all(issubclass(step_type, ActionStep) for step_type in
               (FollowupRequestStep, NotifyStep, ExportStep))


@pytest.mark.parametrize("step_type, kwargs", [
    (SemanticSearchStep, {}),
    (ConeSearchStep, {"ra": 1, "dec": 2, "radius": 0.1}),
    (SqlQueryStep, {"query": "SELECT * FROM records"}),
])
def test_every_concrete_search_requires_semantic_type(step_type, kwargs):
    with pytest.raises(ValidationError, match="semantic_type"):
        step_type(**kwargs)


def test_heterogeneous_workflow_round_trip_preserves_concrete_types():
    workflow = WorkflowIR(name="candidate workflow", steps=concrete_steps())
    reconstructed = WorkflowIR.model_validate(workflow.model_dump())
    assert [type(step) for step in reconstructed.steps] == [type(step) for step in workflow.steps]
    assert reconstructed == workflow


def test_discriminated_union_reconstructs_from_plain_dictionaries():
    workflow = WorkflowIR.model_validate({"steps": [
        {"op": "semantic_search", "semantic_type": "summary"},
        {"op": "lightcurve", "bands": ["g"]},
        {"op": "utility_score", "params": {"objective": "early spectrum"}},
    ]})
    assert isinstance(workflow.steps[0], SemanticSearchStep)
    assert isinstance(workflow.steps[1], LightcurveStep)
    assert isinstance(workflow.steps[2], UtilityScoreStep)


def test_classification_retrieval_and_execution_remain_distinct():
    workflow = WorkflowIR(steps=[GetClassificationStep(), ClassifyStep(method="model-v1")])
    reconstructed = WorkflowIR.model_validate(workflow.model_dump())
    assert type(reconstructed.steps[0]) is GetClassificationStep
    assert type(reconstructed.steps[1]) is ClassifyStep
    assert [step.op for step in reconstructed.steps] == ["get_classification", "classify"]


def test_method_analysis_supports_open_algorithm_vocabulary():
    step = MethodAnalysisStep(method="periodicity")
    assert step.method == "periodicity"
    assert step.sources == []


@pytest.mark.parametrize("identifier", ["ZTF24abc", "alert:survey:123", "source/456"])
def test_lookup_accepts_generic_identifier_namespaces(identifier):
    assert LookupStep(id=identifier).id == identifier


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_required_strings_are_rejected(value):
    with pytest.raises(ValidationError):
        LookupStep(id=value)
    with pytest.raises(ValidationError):
        MethodAnalysisStep(method=value)


def test_source_requires_broker_or_origin():
    with pytest.raises(ValidationError, match="broker or origin"):
        Source()
    assert Source(broker="fink").origin is None
    assert Source(origin="ztf").broker is None


def test_time_context_rejects_reversed_range():
    with pytest.raises(ValidationError, match="start_time"):
        TimeContext(start_time=datetime(2025, 1, 2, tzinfo=timezone.utc),
                    end_time=datetime(2025, 1, 1, tzinfo=timezone.utc))


@pytest.mark.parametrize("kwargs", [
    {"ra": 0, "dec": 0, "radius": 0}, {"ra": 360, "dec": 0, "radius": 1},
    {"ra": -0.1, "dec": 0, "radius": 1}, {"ra": 1, "dec": 90.1, "radius": 1},
    {"ra": 1, "dec": -90.1, "radius": 1},
])
def test_cone_search_rejects_invalid_coordinates_or_radius(kwargs):
    with pytest.raises(ValidationError):
        ConeSearchStep(semantic_type="detection", **kwargs)


def test_crossmatch_radius_must_be_positive():
    with pytest.raises(ValidationError):
        GetCrossmatchStep(radius=-1)


def test_confirmation_validates_required_agreement():
    with pytest.raises(ValidationError):
        ConfirmStep(required_agreement=0)
    with pytest.raises(ValidationError, match="source count"):
        ConfirmStep(required_agreement=2, sources=[Source(broker="fink")])
    assert ConfirmStep(required_agreement=3).sources == []


def test_target_collection_validation_and_round_trip():
    step = GetLightcurveStep(target_ids=["B", "A"])
    assert step.target_id is None
    assert step.target_ids == ["B", "A"]
    workflow = WorkflowIR(steps=[step])
    restored = WorkflowIR.model_validate(workflow.model_dump())
    assert restored.steps[0].target_id is None
    assert restored.steps[0].target_ids == ["B", "A"]

    for invalid in ([], [""], ["A", "A"]):
        with pytest.raises(ValidationError):
            GetLightcurveStep(target_ids=invalid)
    with pytest.raises(ValidationError):
        GetLightcurveStep(target_id="A", target_ids=["B"])
