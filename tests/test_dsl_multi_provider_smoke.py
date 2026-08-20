"""End-to-end DSL candidate discovery feeding cross-provider enrichment."""

from alertissimo.orchestration.runtime import CandidateInputRef
from scripts.smoke.reporting import report_data
from scripts.smoke.scenarios import DSL_MULTI_PROVIDER_SOURCE, run_scenario


def _object_ids(step_output):
    return {
        str(value)
        for execution in step_output.executions
        for portfolio in execution.portfolios
        for record in portfolio.records
        if record.semantic_type.split("@", 1)[0] == "summary"
        for key, value in record.fields.items()
        if key == "identity.object_id" and value is not None
    }


def test_dsl_multi_provider_discovers_candidate_then_late_binds_enrichments():
    result = run_scenario("dsl-multi-provider")

    assert result.dsl_source == DSL_MULTI_PROVIDER_SOURCE
    assert [step.op for step in result.workflow.steps] == [
        "cone_search",
        "get_lightcurve",
        "get_lightcurve",
    ]
    assert all(getattr(step, "target", None) is None for step in result.workflow.steps)

    search_plan = result.run.steps[0].endpoint_plans[0]
    fink_plan = result.run.steps[1].endpoint_plans[0]
    lasair_plan = result.run.steps[2].endpoint_plans[0]

    assert (
        search_plan.broker,
        search_plan.origin,
        search_plan.endpoint,
    ) == ("lasair", "ztf", "cone")
    assert (
        fink_plan.broker,
        fink_plan.origin,
        fink_plan.endpoint,
    ) == ("fink", "ztf", "objects")
    assert (
        lasair_plan.broker,
        lasair_plan.origin,
        lasair_plan.endpoint,
    ) == ("lasair", "ztf", "lightcurves")
    assert fink_plan.candidate_input_from == CandidateInputRef(step_index=0)
    assert lasair_plan.candidate_input_from == CandidateInputRef(step_index=0)
    assert fink_plan.execution_reuse_from is None
    assert lasair_plan.execution_reuse_from is None

    # The semantic GetSteps stay targetless; only physical binding receives the
    # object identity discovered by the normalized candidate search.
    assert result.bindings[1].bound_calls[0].params == {
        "objectId": "ZTF20acpwljl"
    }
    assert result.bindings[2].bound_calls[0].params == {
        "objectIds": "ZTF20acpwljl"
    }

    assert result.normalized is not None
    assert _object_ids(result.normalized.steps[0]) == {"ZTF20acpwljl"}
    assert _object_ids(result.normalized.steps[1]) == {"ZTF20acpwljl"}
    assert _object_ids(result.normalized.steps[2]) == {"ZTF20acpwljl"}

    report = report_data(result)
    assert report["physical_execution_count"] == 3
    assert report["steps"][1]["calls"][0]["candidate_input_from"] == {
        "step_index": 0
    }
    assert report["steps"][2]["calls"][0]["candidate_input_from"] == {
        "step_index": 0
    }
