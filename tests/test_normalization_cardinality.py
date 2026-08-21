"""Offline regression tests for execution-local astronomical-object cardinality."""

from itertools import count

import pytest
import yaml

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
    InternalPortfolioId,
    InternalRecordId,
)
from alertissimo.data_layer.runtime.record_builder import (
    PortfolioBuildError,
    build_portfolio_from_execution,
    build_portfolios_from_execution,
)


def execution(payload):
    return ExecutionResult(
        payload,
        InternalExecutionProvenance(
            InternalExecutionId("execution:test"), "alerce", "ztf", "search"
        ),
    )


def mapping(tmp_path, payloads=None):
    document = {
        "broker": "alerce",
        "origin": "ztf",
        "payloads": payloads
        or {
            "rows": {
                "endpoint": "search",
                "path": "[]",
                "object_partition": {"mode": "field", "field": "oid"},
            }
        },
        "mappings": {
            "summary@ztf:alerce.identity.object_id": ["rows#oid"],
            "summary@ztf:alerce.position.ra": ["rows#ra"],
        },
    }
    path = tmp_path / "mappings.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    return path


def build(tmp_path, payload, **kwargs):
    ids = count()
    return build_portfolios_from_execution(
        execution(payload),
        mappings_path=mapping(tmp_path),
        record_id_factory=lambda: InternalRecordId(f"record:{next(ids)}"),
        **kwargs,
    )


def test_empty_response_produces_no_portfolio(tmp_path):
    assert build(tmp_path, []) == ()


def test_mapped_non_object_response_produces_no_portfolio(tmp_path):
    payloads = {
        "rows": {
            "endpoint": "search",
            "path": "[]",
            "object_partition": {"mode": "none"},
        }
    }
    path = mapping(tmp_path, payloads)
    result = build_portfolios_from_execution(
        execution([{"oid": "A", "ra": 1}]), mappings_path=path
    )
    assert result == ()
    with pytest.raises(PortfolioBuildError, match="found 0"):
        build_portfolio_from_execution(
            execution([{"oid": "A", "ra": 1}]), mappings_path=path
        )


def test_repeated_rows_are_grouped_by_explicit_object_identity(tmp_path):
    portfolios = build(
        tmp_path,
        [
            {"oid": "A", "ra": 1},
            {"oid": "A", "ra": 2},
            {"oid": "B", "ra": 3},
            {"oid": "B", "ra": 4},
            {"oid": "B", "ra": 5},
        ],
    )
    assert [len(p.records) for p in portfolios] == [2, 3]
    assert [
        {r.fields["identity.object_id"] for r in p.records} for p in portfolios
    ] == [{"A"}, {"B"}]
    assert len({p.internal_portfolio_id for p in portfolios}) == 2
    assert len({r.internal_record_id for p in portfolios for r in p.records}) == 5
    assert all(p.executions == (execution([]).execution_provenance,) for p in portfolios)


def test_field_and_root_field_branches_combine_per_object(tmp_path):
    payloads = {
        "rows": {
            "endpoint": "search",
            "path": "[]",
            "object_partition": {"mode": "field", "field": "oid"},
        },
        "candidates": {
            "endpoint": "search",
            "path": "[].candidates[]",
            "object_partition": {"mode": "root_field", "field": "oid"},
        },
    }
    document = {
        "broker": "alerce",
        "origin": "ztf",
        "payloads": payloads,
        "mappings": {
            "summary@ztf:alerce.identity.object_id": ["rows#oid"],
            "detection@ztf:alerce.position.ra": ["candidates#ra"],
        },
    }
    path = tmp_path / "root.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    result = build_portfolios_from_execution(
        execution(
            [
                {"oid": "A", "candidates": [{"ra": 1}, {"ra": 2}]},
                {"oid": "B", "candidates": [{"ra": 3}]},
            ]
        ),
        mappings_path=path,
    )
    assert [len(p.records) for p in result] == [3, 2]
    assert [r.internal_source.payload_index for r in result[0].records] == [0, 0, 1]


def test_partition_identity_seeds_id_only_summary_when_only_detections_are_mapped(
    tmp_path,
):
    document = {
        "broker": "alerce",
        "origin": "ztf",
        "payloads": {
            "rows": {
                "endpoint": "search",
                "path": "[]",
                "object_partition": {"mode": "field", "field": "oid"},
            }
        },
        "mappings": {"detection@ztf:alerce.position.ra": ["rows#ra"]},
    }
    path = tmp_path / "detections-only.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False))

    portfolios = build_portfolios_from_execution(
        execution([{"oid": "A", "ra": 1}, {"oid": "B", "ra": 2}]),
        mappings_path=path,
    )

    assert len(portfolios) == 2
    assert [
        {
            record.fields["identity.object_id"]
            for record in portfolio.records
            if record.semantic_type == "summary@ztf:alerce"
        }
        for portfolio in portfolios
    ] == [{"A"}, {"B"}]


def test_single_target_request_seeds_id_only_summary_when_payload_has_no_object_id(
    tmp_path,
):
    root = tmp_path / "providers"
    provider = root / "alerce" / "ztf"
    provider.mkdir(parents=True)
    (provider / "endpoints.yaml").write_text(
        yaml.safe_dump(
            {
                "broker": "alerce",
                "origin": "ztf",
                "baseurl": "https://example.invalid",
                "transport_defaults": {"kind": "rest"},
                "endpoints": {
                    "search": {
                        "path": "/search",
                        "method": "POST",
                        "params": {
                            "oid": {
                                "required": True,
                                "type": "string",
                                "bind": "target_id",
                            }
                        },
                    }
                },
            },
            sort_keys=False,
        )
    )
    (provider / "mappings.yaml").write_text(
        yaml.safe_dump(
            {
                "broker": "alerce",
                "origin": "ztf",
                "payloads": {
                    "rows": {
                        "endpoint": "search",
                        "path": "[]",
                        "object_partition": {"mode": "single"},
                    }
                },
                "mappings": {"detection@ztf:alerce.position.ra": ["rows#ra"]},
            },
            sort_keys=False,
        )
    )
    requested = ExecutionResult(
        payload=[{"ra": 1}, {"ra": 2}],
        execution_provenance=InternalExecutionProvenance(
            InternalExecutionId("execution:targeted"),
            "alerce",
            "ztf",
            "search",
            params={"oid": "A"},
        ),
    )

    (portfolio,) = build_portfolios_from_execution(requested, providers_root=root)
    summary = next(
        record
        for record in portfolio.records
        if record.semantic_type == "summary@ztf:alerce"
    )
    assert dict(summary.fields) == {"identity.object_id": "A"}
    assert summary.internal_source is None


def test_strict_singular_wrapper_never_selects_or_merges(tmp_path):
    path = mapping(tmp_path)
    with pytest.raises(PortfolioBuildError, match="exactly one"):
        build_portfolio_from_execution(execution([]), mappings_path=path)
    with pytest.raises(PortfolioBuildError, match="exactly one"):
        build_portfolio_from_execution(
            execution([{"oid": "A", "ra": 1}, {"oid": "B", "ra": 2}]),
            mappings_path=path,
        )
    chosen = InternalPortfolioId("portfolio:chosen")
    result = build_portfolio_from_execution(
        execution([{"oid": "A", "ra": 1}]),
        mappings_path=path,
        internal_portfolio_id=chosen,
    )
    assert result.internal_portfolio_id == chosen
    with pytest.raises(PortfolioBuildError, match="internal_portfolio_id"):
        build_portfolios_from_execution(
            execution([]), mappings_path=path, internal_portfolio_id=chosen
        )
