import json
import subprocess
import sys

import pytest

from alertissimo.orchestration.ir import WorkflowIR
from scripts.smoke.reporting import render_human, render_json, report_data
from scripts.smoke.scenarios import (
    BATCH_TARGETS,
    multi_provider_workflow,
    multi_target_workflow,
    run_scenario,
)


def test_scenario_construction_is_valid_ir():
    assert isinstance(multi_provider_workflow(), WorkflowIR)
    assert isinstance(multi_target_workflow(), WorkflowIR)


def test_multi_provider_real_planning_binding_and_normalization():
    result = run_scenario("multi-provider")
    endpoints = [
        (p.broker, p.endpoint) for step in result.run.steps for p in step.endpoint_plans
    ]
    assert endpoints == [
        ("fink", "objects"),
        ("lasair", "lightcurves"),
        ("alerce", "query_forced_photometry"),
        ("alerce", "query_lightcurve"),
    ]
    assert [
        dict(call.params) for binding in result.bindings for call in binding.bound_calls
    ] == [
        {"objectId": "170587117485817955"},
        {"objectIds": "170587117485817955"},
        {"oid": 170587117485817955},
        {"oid": 170587117485817955},
    ]
    assert all(step.state.value == "succeeded" for step in result.run.steps)
    assert report_data(result)["normalized_execution_count"] == 4


def test_multi_target_collection_binding_and_object_safe_portfolios():
    result = run_scenario("multi-target")
    assert (
        len([call for binding in result.bindings for call in binding.bound_calls]) == 2
    )
    assert [dict(binding.bound_calls[0].params) for binding in result.bindings] == [
        {"objectId": ",".join(BATCH_TARGETS)},
        {"objectIds": ",".join(BATCH_TARGETS)},
    ]
    portfolios = [
        p
        for step in result.normalized.steps
        for execution in step.executions
        for p in execution.portfolios
    ]
    assert len(portfolios) == 4
    assert len({p.internal_portfolio_id.value for p in portfolios}) == 4
    for step in result.normalized.steps:
        for execution in step.executions:
            ids = []
            for portfolio in execution.portfolios:
                object_ids = {
                    str(r.fields["identity.object_id"])
                    for r in portfolio.records
                    if "identity.object_id" in r.fields
                }
                if object_ids:
                    assert len(object_ids) == 1
                    ids.extend(object_ids)
                assert (
                    portfolio.executions[0].internal_execution_id.value
                    == execution.execution_id
                )
                assert (
                    portfolio.executions[0].endpoint
                    == result.run.steps[step.step_index].endpoint_plans[0].endpoint
                )
            assert len(ids) == len(set(ids))
    fink = portfolios[0]
    assert len(fink.records_of_type("detection@ztf:fink")) == 2


def test_expected_partial_failure_preserves_runtime_contract():
    result = run_scenario("partial-failure")
    error = result.expected_error
    assert error is not None
    assert result.run.steps[0].execution_ids == ("execution:smoke:1",)
    assert result.run.steps[1].execution_ids == ("execution:smoke:2",)
    assert result.run.steps[1].state.value == "failed"
    assert len(error.completed_steps[0].executions) == 1
    assert len(error.completed_steps[1].executions) == 1


def test_reporting_human_and_json_are_payload_free():
    result = run_scenario("multi-provider")
    human = render_human(result)
    data = json.loads(render_json(result))
    assert "scenario: multi-provider" in human
    assert data["scenario"] == "multi-provider"
    assert "payload" not in render_json(result)


@pytest.mark.parametrize(
    "args", [["--list"], ["multi-provider", "--json"], ["partial-failure"]]
)
def test_cli_success_and_fixture_default_has_no_network(monkeypatch, args):
    import alertissimo.data_layer.execution.transports as transports

    monkeypatch.setattr(
        transports.RestTransport,
        "execute",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")),
    )
    from scripts.smoke.__main__ import main

    assert main(args) == 0


@pytest.mark.parametrize("args", [["unknown"], [], ["--list", "multi-target"]])
def test_cli_rejects_unknown_or_invalid_arguments(args):
    completed = subprocess.run(
        [sys.executable, "-m", "scripts.smoke", *args], text=True, capture_output=True
    )
    assert completed.returncode != 0
    assert "usage:" in completed.stderr
