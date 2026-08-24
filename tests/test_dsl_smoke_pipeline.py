"""End-to-end DSL smoke acceptance from source text to normalized Portfolios."""

from __future__ import annotations

from alertissimo.orchestration.runtime import EndpointPlanRef
from scripts.smoke.reporting import report_data
from scripts.smoke.scenarios import (
    DSL_PIPELINE_CLASSIFIER,
    DSL_PIPELINE_DEC,
    DSL_PIPELINE_RA,
    DSL_PIPELINE_RADIUS_ARCSEC,
    DSL_PIPELINE_SOURCE,
    run_scenario,
)


def _classification_records(step_output):
    return [
        record
        for execution in step_output.executions
        for portfolio in execution.portfolios
        for record in portfolio.records
        if record.semantic_type.split("@", 1)[0] == "classification"
    ]


def test_dsl_pipeline_fixture_compiles_coalesces_executes_and_normalizes():
    result = run_scenario("dsl-pipeline")

    assert result.dsl_source == DSL_PIPELINE_SOURCE
    assert [step.op for step in result.workflow.steps] == [
        "cone_search",
        "get_classification",
    ]

    search_plan = result.run.steps[0].endpoint_plans[0]
    classification_plan = result.run.steps[1].endpoint_plans[0]
    assert (
        search_plan.broker,
        search_plan.origin,
        search_plan.endpoint,
    ) == ("alerce", "lsst", "query_objects")
    assert classification_plan.execution_reuse_from == EndpointPlanRef(
        step_index=0, plan_index=0
    )

    realization = search_plan.predicate_realization
    assert realization is not None
    assert realization.residual is None
    assert realization.params == {
        "classifier": DSL_PIPELINE_CLASSIFIER,
        "class_name": "SN",
        "probability": 0.5,
    }
    assert result.bindings[0].bound_calls[0].params == {
        **realization.params,
        "ra": DSL_PIPELINE_RA,
        "dec": DSL_PIPELINE_DEC,
        "radius": DSL_PIPELINE_RADIUS_ARCSEC,
    }
    assert result.bindings[1].bound_calls[0].params == {}

    execution_ids = [
        step.execution_ids[0]
        for step in result.run.steps
        if step.execution_ids
    ]
    assert len(execution_ids) == 2
    assert len(set(execution_ids)) == 1

    assert result.normalized is not None
    assert len(result.normalized.steps) == 2
    assert all(len(step.executions) == 1 for step in result.normalized.steps)
    assert {
        step.executions[0].execution_id for step in result.normalized.steps
    } == set(execution_ids)

    search_portfolios = result.normalized.steps[0].executions[0].portfolios
    classification_portfolios = result.normalized.steps[1].executions[0].portfolios
    assert len(search_portfolios) == len(classification_portfolios) == 1
    assert search_portfolios[0] is classification_portfolios[0]
    assert (
        search_portfolios[0].internal_portfolio_id.value
        == classification_portfolios[0].internal_portfolio_id.value
    )

    for step_output in result.normalized.steps:
        records = _classification_records(step_output)
        assert records
        assert any(
            record.semantic_type
            == f"classification@{DSL_PIPELINE_CLASSIFIER}:alerce"
            and record.fields.get("best.class") == "SN"
            and record.fields.get("best.probability") == 0.76939845
            for record in records
        )
        assert all(
            provenance.transport == "fixture"
            for execution in step_output.executions
            for portfolio in execution.portfolios
            for provenance in portfolio.executions
        )

    report = report_data(result)
    assert report["normalized_execution_count"] == 2
    assert report["physical_execution_count"] == 1
    assert len(report["physical_execution_ids"]) == 1
    assert report["unique_portfolio_count"] == 1
    assert report["steps"][1]["calls"][0]["reuse_from"] == {
        "step_index": 0,
        "plan_index": 0,
    }
