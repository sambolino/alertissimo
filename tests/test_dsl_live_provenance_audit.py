"""Offline regression for the live accumulated-Portfolio provenance auditor."""

from types import SimpleNamespace

from scripts.live_dsl_provenance_audit import audit_accumulation, audit_portfolio
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
    report = audit_portfolio(portfolio)

    assert report["record_count"] > 0
    assert report["execution_count"] == 3
    assert sum(report["records_by_execution"].values()) == report["record_count"]
    assert (
        sum(report["payload_records_by_execution"].values())
        + sum(report["request_records_by_execution"].values())
        == report["record_count"]
    )
    # Lasair's target-bound lightcurve fixture has no mapped summary of its own,
    # so record_builder correctly synthesizes the minimal object identity from the
    # declared target-id request binding rather than inventing a payload coordinate.
    assert sum(report["request_records_by_execution"].values()) >= 1
    assert set(report["records_by_execution"]) == {
        execution.internal_execution_id.value
        for execution in portfolio.executions
    }
