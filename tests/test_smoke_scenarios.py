import json
import subprocess
import sys
from pathlib import Path

import pytest

from alertissimo.orchestration.ir import WorkflowIR
from scripts.smoke.reporting import render_human, render_json, report_data
from scripts.smoke.scenarios import (
    BATCH_TARGETS,
    DEFAULT_TARGET,
    multi_provider_workflow,
    multi_target_workflow,
    partial_failure_workflow,
    run_scenario,
)


def test_scenario_construction_is_valid_ir_and_all_ztf():
    workflow = multi_provider_workflow()
    assert isinstance(workflow, WorkflowIR)
    assert isinstance(multi_target_workflow(), WorkflowIR)
    assert DEFAULT_TARGET == "ZTF18abbuksn"
    assert {step.target.ids[0] for step in workflow.steps} == {DEFAULT_TARGET}
    assert {source.origin for step in workflow.steps for source in step.sources} == {
        "ztf"
    }
    assert {
        source.origin
        for step in partial_failure_workflow().steps
        for source in step.sources
    } == {"ztf"}


def test_multi_provider_real_planning_binding_and_normalization():
    result = run_scenario("multi-provider")
    endpoints = [
        (p.broker, p.origin, p.endpoint)
        for step in result.run.steps
        for p in step.endpoint_plans
    ]
    assert endpoints == [
        ("fink", "ztf", "objects"),
        ("lasair", "ztf", "lightcurves"),
        ("alerce", "ztf", "query_forced_photometry"),
        ("alerce", "ztf", "query_lightcurve"),
    ]
    assert [
        dict(call.params) for binding in result.bindings for call in binding.bound_calls
    ] == [
        {"objectId": DEFAULT_TARGET},
        {"objectIds": DEFAULT_TARGET},
        {"oid": DEFAULT_TARGET},
        {"oid": DEFAULT_TARGET},
    ]
    assert all(step.state.value == "succeeded" for step in result.run.steps)
    assert report_data(result)["normalized_execution_count"] == 4


def test_single_target_fixture_payload_ids_match_bound_default():
    root = Path("scripts/smoke/fixtures")
    fink = json.loads((root / "fink_objects_single.json").read_text())
    lasair = json.loads((root / "lasair_lightcurves_single.json").read_text())
    assert {row["i:objectId"] for row in fink} == {DEFAULT_TARGET}
    assert {row["objectId"] for row in lasair} == {DEFAULT_TARGET}
    manifest = json.loads(
        Path("tests/fixtures/alerce/ztf/capture_rest_manifest.json").read_text()
    )
    assert manifest["calls"]["query_forced_photometry"]["object"] == DEFAULT_TARGET
    assert manifest["calls"]["query_lightcurve"]["object"] == DEFAULT_TARGET


def test_multi_target_collection_binding_and_honest_object_identity():
    result = run_scenario("multi-target")
    assert (
        len([call for binding in result.bindings for call in binding.bound_calls]) == 2
    )
    assert [dict(binding.bound_calls[0].params) for binding in result.bindings] == [
        {"objectId": ",".join(BATCH_TARGETS)},
        {"objectIds": ",".join(BATCH_TARGETS)},
    ]
    fink_output = result.normalized.steps[0].executions[0]
    lasair_output = result.normalized.steps[1].executions[0]
    assert len(fink_output.portfolios) == len(BATCH_TARGETS)
    found = []
    for portfolio in fink_output.portfolios:
        object_ids = [
            str(r.fields["identity.object_id"])
            for r in portfolio.records
            if "identity.object_id" in r.fields
        ]
        assert object_ids
        assert set(object_ids).__len__() == 1
        found.append(object_ids[0])
        assert (
            portfolio.executions[0].internal_execution_id.value
            == fink_output.execution_id
        )
        assert portfolio.executions[0].endpoint == "objects"
    assert set(found) == set(BATCH_TARGETS)
    assert len(found) == len(set(found))
    assert len(fink_output.portfolios[0].records_of_type("detection@ztf:fink")) == 2

    assert len(lasair_output.portfolios) == len(BATCH_TARGETS)
    all_portfolios = fink_output.portfolios + lasair_output.portfolios
    assert len({p.internal_portfolio_id.value for p in all_portfolios}) == len(
        all_portfolios
    )
    for portfolio in lasair_output.portfolios:
        assert not any(
            "identity.object_id" in record.fields for record in portfolio.records
        )
        assert (
            portfolio.executions[0].internal_execution_id.value
            == lasair_output.execution_id
        )
        assert portfolio.executions[0].endpoint == "lightcurves"
    report = report_data(result)
    assert report["steps"][1]["requested_target_ids"] == list(BATCH_TARGETS)
    assert all(
        not p["object_identity_available"] and p["object_ids"] == []
        for p in report["steps"][1]["executions"][0]["portfolios"]
    )
    assert "object identity: unavailable" in render_human(result)


def test_expected_partial_failure_preserves_and_reports_runtime_contract():
    result = run_scenario("partial-failure")
    error = result.expected_error
    assert error is not None
    assert result.run.steps[0].execution_ids == ("execution:smoke:1",)
    assert result.run.steps[1].execution_ids == ("execution:smoke:2",)
    assert result.run.steps[1].state.value == "failed"
    assert len(error.completed_steps[0].executions) == 1
    assert len(error.completed_steps[1].executions) == 1
    data = json.loads(render_json(result))
    human = render_human(result)
    assert data["expected_failure"] is True
    assert data["failed_step_index"] == 1
    assert "controlled fixture failure" in data["failure_error"]
    assert data["preserved_execution_ids"] == ["execution:smoke:1", "execution:smoke:2"]
    assert "expected failure: yes" in human
    assert "failed step: 1" in human
    assert "controlled fixture failure" in human
    assert "execution:smoke:1" in human and "execution:smoke:2" in human


def test_reporting_json_is_payload_free():
    data = json.loads(render_json(run_scenario("multi-provider")))
    assert data["scenario"] == "multi-provider"
    assert "payload" not in json.dumps(data)


def test_fixture_custom_targets_rejected_programmatically_before_planning(monkeypatch):
    monkeypatch.setattr(
        "scripts.smoke.scenarios.plan_workflow",
        lambda *a: (_ for _ in ()).throw(AssertionError("planned")),
    )
    with pytest.raises(ValueError, match="custom targets require live=True"):
        run_scenario("multi-provider", targets=("ZTF-custom",))


def test_live_target_override_reaches_construction_without_execution(monkeypatch):
    class Stop(Exception):
        pass

    def stop(workflow, graph):
        assert workflow.steps[0].target.ids == ["ZTF-custom"]
        raise Stop

    monkeypatch.setattr("scripts.smoke.scenarios.plan_workflow", stop)
    with pytest.raises(Stop):
        run_scenario("multi-provider", live=True, targets=("ZTF-custom",))


def test_partial_failure_live_rejected_before_planning(monkeypatch):
    monkeypatch.setattr(
        "scripts.smoke.scenarios.plan_workflow",
        lambda *a: (_ for _ in ()).throw(AssertionError("planned")),
    )
    with pytest.raises(ValueError, match="fixture-only"):
        run_scenario("partial-failure", live=True)


def test_cli_accepts_live_target_override_without_executing(monkeypatch):
    from scripts.smoke import __main__ as cli

    class StopBeforeExecution(Exception):
        pass

    def stop(name, *, live, targets):
        assert name == "multi-provider"
        assert live is True
        assert targets == ("ZTF-custom",)
        raise StopBeforeExecution

    monkeypatch.setattr(cli, "run_scenario", stop)
    with pytest.raises(StopBeforeExecution):
        cli.main(["multi-provider", "--live", "--target", "ZTF-custom"])


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
    monkeypatch.setattr(
        "alertissimo.data_layer.execution.RegistryEndpointExecutor.execute",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("provider execution")),
    )
    from scripts.smoke.__main__ import main

    assert main(args) == 0


@pytest.mark.parametrize(
    "args, message",
    [
        (["unknown"], "invalid choice"),
        ([], "scenario is required"),
        (["--list", "multi-target"], "--list cannot be combined"),
        (["multi-provider", "--target", "ZTF-custom"], "--target requires --live"),
        (["partial-failure", "--live"], "fixture-only"),
    ],
)
def test_cli_rejects_unknown_or_invalid_arguments(args, message):
    completed = subprocess.run(
        [sys.executable, "-m", "scripts.smoke", *args], text=True, capture_output=True
    )
    assert completed.returncode != 0
    assert "usage:" in completed.stderr
    assert message in completed.stderr
