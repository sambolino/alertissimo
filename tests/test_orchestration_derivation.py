"""End-to-end contracts for local post-normalization DeriveStep operations."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from alertissimo.data_layer.representations import (
    InternalPortfolioId,
    InternalRecordId,
    Portfolio,
    SemanticRecord,
)
from alertissimo.data_layer.semantic_model import load_semantic_model_index
from alertissimo.orchestration.derivation import (
    UnsupportedDerivationError,
    derive_portfolio,
)
from alertissimo.orchestration.ir import (
    ColorColorStep,
    ColorMagnitudeStep,
    DeriveStep,
    LightcurveStep,
)
from scripts.smoke.scenarios import run_scenario


def _color_portfolio() -> Portfolio:
    return Portfolio(
        internal_portfolio_id=InternalPortfolioId("portfolio:colors"),
        records=(
            SemanticRecord(
                internal_record_id=InternalRecordId("record:lightcurve"),
                semantic_type="lightcurve@test",
                fields={
                    "color_points": (
                        {
                            "time.mjd": 60000.0,
                            "color.g-r.diff": 0.4,
                            "color.g-r.error": 0.03,
                        },
                        {
                            "time.mjd": 60000.0,
                            "color.r-i.diff": 0.2,
                            "color.r-i.error": 0.04,
                        },
                    )
                },
            ),
        ),
    )


def test_derive_hierarchy_and_scientific_parameters_are_explicit():
    assert issubclass(LightcurveStep, DeriveStep)
    assert issubclass(ColorMagnitudeStep, DeriveStep)
    assert issubclass(ColorColorStep, DeriveStep)

    step = ColorMagnitudeStep(
        color="g-r",
        magnitude_field="photometry.r.psf.mag",
        max_time_delta=timedelta(minutes=30),
    )
    assert step.magnitude_field == "photometry.r.psf.mag"
    assert step.max_time_delta == timedelta(minutes=30)

    with pytest.raises(ValidationError, match="non-negative"):
        ColorMagnitudeStep(
            color="g-r",
            magnitude_field="photometry.r.psf.mag",
            max_time_delta=timedelta(seconds=-1),
        )
    with pytest.raises(ValidationError, match="distinct"):
        ColorColorStep(color_x="g-r", color_y="g-r")


def test_complete_workflow_derives_color_magnitude_into_its_own_step_view():
    result = run_scenario("color-magnitude")

    assert [step.state.value for step in result.run.steps] == [
        "succeeded",
        "succeeded",
    ]
    assert len(result.bindings[0].bound_calls) == 1
    assert result.bindings[1].bound_calls == ()
    assert result.run.steps[1].endpoint_plans == ()
    assert result.run.steps[1].execution_ids == ()
    assert result.run.steps[1].material_input_from is not None
    assert result.run.steps[1].material_input_from.step_index == 0

    provider_output = result.normalized.steps[0].executions[0]
    assert len(provider_output.portfolios) == 1
    provider_portfolio = provider_output.portfolios[0]
    assert provider_portfolio.records_of_type("color_magnitude@alertissimo") == ()

    derive_output = result.normalized.steps[1]
    assert derive_output.executions == ()
    assert len(derive_output.portfolios) == 1
    portfolio = derive_output.portfolios[0]
    (derived,) = portfolio.records_of_type("color_magnitude@alertissimo")
    assert derived.internal_source is None
    assert derived.fields["points"] == (
        {
            "color.g-r.diff": 0.2,
            "color.g-r.error": 0.05,
            "photometry.r.psf.mag": 18.9,
            "photometry.r.psf.mag.error": 0.1,
        },
    )
    assert len(portfolio.executions) == 1
    assert portfolio.executions[0].broker == "fink"
    assert portfolio.executions[0].endpoint == "objects"

    # The derivation is a new immutable semantic snapshot, not a retroactive rewrite.
    assert portfolio.internal_portfolio_id == provider_portfolio.internal_portfolio_id
    assert len(portfolio.records) == len(provider_portfolio.records) + 1


def test_color_color_derivation_produces_non_temporal_semantic_points():
    derived = derive_portfolio(
        ColorColorStep(color_x="g-r", color_y="r-i"),
        _color_portfolio(),
        step_index=2,
    )

    (record,) = derived.records_of_type("color_color@alertissimo")
    assert record.internal_source is None
    assert record.fields["points"] == (
        {
            "color.g-r.diff": 0.4,
            "color.g-r.error": 0.03,
            "color.r-i.diff": 0.2,
            "color.r-i.error": 0.04,
        },
    )
    assert "time.mjd" not in record.fields["points"][0]


def test_target_scoped_derivation_does_not_guess_portfolio_identity():
    from alertissimo.orchestration.ir import TargetSelector

    with pytest.raises(UnsupportedDerivationError, match="Portfolio-to-target"):
        derive_portfolio(
            ColorColorStep(
                color_x="g-r",
                color_y="r-i",
                target=TargetSelector(ids=["ZTF18abbuksn"], kind="object"),
            ),
            _color_portfolio(),
            step_index=2,
        )


def test_ontology_declares_direct_color_relation_products():
    index = load_semantic_model_index()
    assert {"color_magnitude", "color_color"} <= index.containers
