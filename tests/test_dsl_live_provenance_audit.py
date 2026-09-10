"""Offline regressions for the live accumulated-Portfolio provenance auditor."""

from types import SimpleNamespace

from scripts.live_dsl_provenance_audit import (
    _cumulative_record_execution_owners,
    audit_accumulation,
    audit_portfolio,
)
from scripts.smoke.scenarios import run_scenario


def test_offline_multi_provider_portfolio_is_fully_traceable():
    result = run_scenario("dsl-multi-provider")
    assert result.normalized is not None

    staged_like = SimpleNamespace(run=result.run, normalized=result.normalized)
    expected_found, detail = audit_accumulation(
        staged_like,
        expected_object_id="ZTF20acpwljl",
    )

    assert expected_found
    assert "every final record resolves" in detail
    assert "target-bound request" in detail
    assert "inherited record/execution provenance remained immutable" in detail

    final = result.normalized.steps[-1]
    assert len(final.portfolios) == 1
    portfolio = final.portfolios[0]
    owners = _cumulative_record_execution_owners(result.normalized.steps)
    report = audit_portfolio(portfolio, record_execution_owners=owners)

    assert report["record_count"] > 0
    assert report["execution_count"] == 3
    assert sum(report["records_by_execution"].values()) == report["record_count"]
    assert (
        sum(report["payload_records_by_execution"].values())
        + sum(report["request_records_by_execution"].values())
        + sum(report["aggregate_records_by_execution"].values())
        == report["record_count"]
    )
    assert sum(report["request_records_by_execution"].values()) >= 1
    assert set(report["records_by_execution"]) == {
        execution.internal_execution_id.value
        for execution in portfolio.executions
    }


def test_alerce_multisurface_lightcurve_uses_occurrence_local_execution_owner():
    """ALeRCE detections + non-detections collapse into one source-less aggregate."""

    result = run_scenario("multi-provider")
    assert result.normalized is not None

    alerce_lightcurve_step = result.normalized.steps[-1]
    assert len(alerce_lightcurve_step.portfolios) == 1
    portfolio = alerce_lightcurve_step.portfolios[0]
    owners = _cumulative_record_execution_owners(result.normalized.steps)
    report = audit_portfolio(portfolio, record_execution_owners=owners)

    query_lightcurve_ids = {
        execution.internal_execution_id.value
        for execution in portfolio.executions
        if execution.broker == "alerce"
        and execution.origin == "ztf"
        and execution.endpoint == "query_lightcurve"
    }
    assert len(query_lightcurve_ids) == 1
    execution_id = next(iter(query_lightcurve_ids))

    assert report["aggregate_records_by_execution"][execution_id] == 1
    assert report["request_records_by_execution"][execution_id] == 1
    assert report["semantic_types_by_execution"][execution_id]["lightcurve@ztf:alerce"] == 1
    assert (
        report["payload_records_by_execution"][execution_id]
        + report["request_records_by_execution"][execution_id]
        + report["aggregate_records_by_execution"][execution_id]
        == report["records_by_execution"][execution_id]
    )
