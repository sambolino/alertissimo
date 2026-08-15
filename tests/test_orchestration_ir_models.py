"""Focused tests for the provider-independent orchestration IR."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from alertissimo.orchestration.ir import (
    AggregateStep, AnalyzeStep, ClassifyStep, CompareStep, ConeSearchStep,
    ConfirmStep, CrossmatchStep, CutoutStep, ExportStep, FilterStep,
    FollowupRequestStep, ForcedPhotometryStep, GetClassificationStep,
    GetDataProductStep, GetSpectrumStep, LightcurveStep, LookupStep, MonitorStep,
    NotifyStep, SearchStep, Source, SqlQueryStep, TimeContext, UtilityScoreStep,
    WorkflowIR,
)


def concrete_steps():
    """Return one valid instance of every concrete operation in the census."""
    source = Source(broker="fink", origin="ztf")
    time = TimeContext(start_time="2025-01-01T00:00:00Z", end_time="2025-01-02T00:00:00Z")
    return [
        LookupStep(id="ZTF-object-or-alert", sources=[source]),
        SearchStep(semantic_type="object", criteria={"classification": "SN"}, time_context=time),
        FilterStep(criteria={"magnitude": {"lt": 20}}),
        ConeSearchStep(ra=12.5, dec=-20, radius=0.1, magnitude_limit=21),
        SqlQueryStep(query="SELECT object_id FROM objects"),
        LightcurveStep(target_id="target", bands=["g", "r"], time_context=time),
        CrossmatchStep(target_id="target", catalog="gaia", radius=1.0),
        CutoutStep(target_id="target", format="fits", size=30),
        ForcedPhotometryStep(target_id="target", bands=["g"], time_context=time),
        GetClassificationStep(target_id="target"),
        GetSpectrumStep(target_id="target", time_context=time),
        GetDataProductStep(target_id="target", product_type="image"),
        AnalyzeStep(target_id="target", method="periodicity", params={"period_min": 1}),
        ClassifyStep(target_id="target", method="random_forest"),
        AggregateStep(method="mean", field="photometry.flux", group_by=["band"]),
        CompareStep(target="classification", method="disagreement"),
        ConfirmStep(target_id="target", required_agreement=1, sources=[source]),
        UtilityScoreStep(target_id="target", method="followup_priority"),
        MonitorStep(stream="alerts", criteria={"survey": "ztf"}),
        FollowupRequestStep(request_type="spectroscopy", target_id="target", facility="generic"),
        NotifyStep(channel="email", recipient="team@example.test", message="Candidate found"),
        ExportStep(destination="portfolio.json", format="json"),
    ]


def test_constructs_every_concrete_step():
    steps = concrete_steps()
    assert len(steps) == 22
    assert len({step.op for step in steps}) == len(steps)


def test_heterogeneous_workflow_round_trip_preserves_concrete_types():
    workflow = WorkflowIR(name="candidate workflow", steps=concrete_steps())
    reconstructed = WorkflowIR.model_validate(workflow.model_dump())
    assert [type(step) for step in reconstructed.steps] == [type(step) for step in workflow.steps]
    assert reconstructed == workflow


def test_discriminated_union_reconstructs_from_plain_dictionaries():
    workflow = WorkflowIR.model_validate({"steps": [
        {"op": "lookup", "id": "alert-123"},
        {"op": "lightcurve", "bands": ["g"]},
        {"op": "utility_score", "params": {"objective": "early spectrum"}},
    ]})
    assert isinstance(workflow.steps[0], LookupStep)
    assert isinstance(workflow.steps[1], LightcurveStep)
    assert isinstance(workflow.steps[2], UtilityScoreStep)


def test_classification_retrieval_and_execution_remain_distinct():
    workflow = WorkflowIR(steps=[GetClassificationStep(), ClassifyStep(method="model-v1")])
    reconstructed = WorkflowIR.model_validate(workflow.model_dump())
    assert type(reconstructed.steps[0]) is GetClassificationStep
    assert type(reconstructed.steps[1]) is ClassifyStep
    assert [step.op for step in reconstructed.steps] == ["get_classification", "classify"]


@pytest.mark.parametrize("identifier", ["ZTF24abc", "alert:survey:123", "source/456"])
def test_lookup_accepts_generic_identifier_namespaces(identifier):
    assert LookupStep(id=identifier).id == identifier


def test_analysis_method_is_open_vocabulary_and_sources_are_optional():
    step = AnalyzeStep(method="periodicity")
    assert step.method == "periodicity"
    assert step.sources == []


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_required_strings_are_rejected(value):
    with pytest.raises(ValidationError):
        LookupStep(id=value)
    with pytest.raises(ValidationError):
        AnalyzeStep(method=value)


def test_source_requires_broker_or_origin():
    with pytest.raises(ValidationError, match="broker or origin"):
        Source()
    assert Source(broker="fink").origin is None
    assert Source(origin="ztf").broker is None


def test_time_context_rejects_reversed_range():
    with pytest.raises(ValidationError, match="start_time"):
        TimeContext(
            start_time=datetime(2025, 1, 2, tzinfo=timezone.utc),
            end_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )


@pytest.mark.parametrize("kwargs", [
    {"ra": 0, "dec": 0, "radius": 0},
    {"ra": 360, "dec": 0, "radius": 1},
    {"ra": -0.1, "dec": 0, "radius": 1},
    {"ra": 1, "dec": 90.1, "radius": 1},
    {"ra": 1, "dec": -90.1, "radius": 1},
])
def test_cone_search_rejects_invalid_coordinates_or_radius(kwargs):
    with pytest.raises(ValidationError):
        ConeSearchStep(**kwargs)


def test_crossmatch_radius_must_be_positive():
    with pytest.raises(ValidationError):
        CrossmatchStep(radius=-1)


def test_confirmation_validates_required_agreement():
    with pytest.raises(ValidationError):
        ConfirmStep(required_agreement=0)
    with pytest.raises(ValidationError, match="source count"):
        ConfirmStep(required_agreement=2, sources=[Source(broker="fink")])
    assert ConfirmStep(required_agreement=3).sources == []
