"""Regression tests for semantic identity completion on target-bound retrievals."""

import yaml

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
)
from alertissimo.data_layer.runtime.record_builder import build_portfolios_from_execution


def _provider_root(tmp_path, *, partition):
    root = tmp_path / "providers"
    provider = root / "testbroker" / "testorigin"
    provider.mkdir(parents=True)
    (provider / "endpoints.yaml").write_text(
        yaml.safe_dump(
            {
                "broker": "testbroker",
                "origin": "testorigin",
                "baseurl": "https://example.invalid",
                "transport_defaults": {"kind": "rest"},
                "endpoints": {
                    "retrieve": {
                        "path": "/retrieve",
                        "method": "GET",
                        "params": {
                            "ids": {
                                "required": True,
                                "type": "string",
                                "bind": "target_id",
                                "binding": {"collection": "csv"},
                            }
                        },
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (provider / "mappings.yaml").write_text(
        yaml.safe_dump(
            {
                "broker": "testbroker",
                "origin": "testorigin",
                "payloads": {
                    "rows": {
                        "endpoint": "retrieve",
                        "path": "[]",
                        "object_partition": partition,
                    }
                },
                "mappings": {
                    "detection@testorigin:testbroker.position.ra": ["rows#ra"]
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return root


def _execution(payload):
    return ExecutionResult(
        payload=payload,
        execution_provenance=InternalExecutionProvenance(
            InternalExecutionId("execution:target-bound"),
            "testbroker",
            "testorigin",
            "retrieve",
            params={"ids": "A,B"},
        ),
    )


def test_multi_target_partition_identity_seeds_one_summary_per_portfolio(tmp_path):
    root = _provider_root(
        tmp_path,
        partition={"mode": "field", "field": "oid"},
    )

    portfolios = build_portfolios_from_execution(
        _execution(
            [
                {"oid": "A", "ra": 1.0},
                {"oid": "A", "ra": 1.1},
                {"oid": "B", "ra": 2.0},
            ]
        ),
        providers_root=root,
    )

    assert len(portfolios) == 2
    found = []
    for portfolio in portfolios:
        summaries = [
            record
            for record in portfolio.records
            if record.semantic_type == "summary@testorigin:testbroker"
        ]
        assert len(summaries) == 1
        assert summaries[0].internal_source is None
        found.append(summaries[0].fields["identity.object_id"])
    assert set(found) == {"A", "B"}


def test_multi_target_single_partition_does_not_guess_identity(tmp_path):
    root = _provider_root(tmp_path, partition={"mode": "single"})

    (portfolio,) = build_portfolios_from_execution(
        _execution([{"ra": 1.0}, {"ra": 2.0}]),
        providers_root=root,
    )

    assert not any(
        record.semantic_type.split("@", 1)[0] == "summary"
        for record in portfolio.records
    )
