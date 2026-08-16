"""Offline regressions for execution-to-object normalization cardinality."""
from itertools import count

import pytest
import yaml

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId, InternalExecutionProvenance, InternalRecordId,
)
from alertissimo.data_layer.runtime.record_builder import (
    PortfolioBuildError, build_portfolio_from_execution,
    build_portfolios_from_execution,
)


def _execution(payload, endpoint="objects", execution_id="execution:test"):
    return ExecutionResult(payload=payload, execution_provenance=InternalExecutionProvenance(
        internal_execution_id=InternalExecutionId(execution_id), broker="alerce",
        origin="ztf", endpoint=endpoint,
    ))


def _mapping(tmp_path, payloads):
    document = {
        "broker": "alerce", "origin": "ztf", "payloads": payloads,
        "mappings": {
            "summary@ztf:alerce.identity.object_id": [f"{key}#oid" for key in payloads],
            "summary@ztf:alerce.coordinates.position.ra_deg": [f"{key}#ra" for key in payloads],
        },
    }
    path = tmp_path / "mappings.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    return path


def _build(tmp_path, payload, payloads, **kwargs):
    ids = count()
    return build_portfolios_from_execution(
        _execution(payload), mappings_path=_mapping(tmp_path, payloads),
        record_id_factory=lambda: InternalRecordId(f"record:{next(ids)}"), **kwargs,
    )


def test_empty_response_produces_no_portfolios(tmp_path):
    assert _build(tmp_path, [], {"objects": {"path": "[]", "object_partition": {"mode": "field", "field": "oid"}}}) == ()


def test_rows_are_grouped_by_explicit_object_identifier(tmp_path):
    portfolios = _build(tmp_path, [
        {"oid": "A", "ra": 1}, {"oid": "A", "ra": 2}, {"oid": "B", "ra": 3},
    ], {"objects": {"path": "[]", "object_partition": {"mode": "field", "field": "oid"}}})
    assert len(portfolios) == 2
    assert [{record.get("identity.object_id") for record in portfolio.records} for portfolio in portfolios] == [{"A"}, {"B"}]
    assert [len(portfolio.records) for portfolio in portfolios] == [2, 1]


def test_multiple_single_object_branches_share_one_portfolio(tmp_path):
    payloads = {
        "detections": {"path": "detections[]", "endpoint": "objects", "object_partition": {"mode": "single"}},
        "crossmatches": {"path": "crossmatches[]", "endpoint": "objects", "object_partition": {"mode": "single"}},
    }
    portfolios = _build(tmp_path, {"detections": [{"oid": "A", "ra": 1}, {"oid": "A", "ra": 2}], "crossmatches": [{"oid": "A"}, {"oid": "A"}]}, payloads)
    assert len(portfolios) == 1
    assert len(portfolios[0].records) == 4
    assert {record.internal_source.payload_key for record in portfolios[0].records} == {"detections", "crossmatches"}


def test_nested_observations_use_explicit_root_object_identifier(tmp_path):
    payload = [
        {"oid": "A", "observations": [{"oid": "row", "ra": 1}, {"oid": "row", "ra": 2}]},
        {"oid": "B", "observations": [{"oid": "row", "ra": 3}]},
    ]
    portfolios = _build(tmp_path, payload, {
        "objects": {"path": "[].observations[]", "object_partition": {"mode": "root_field", "field": "oid"}}
    })
    assert [len(portfolio.records) for portfolio in portfolios] == [2, 1]
    assert len({portfolio.internal_portfolio_id for portfolio in portfolios}) == 2


def test_provenance_and_source_coordinates_are_retained(tmp_path):
    portfolios = _build(tmp_path, [{"oid": "A"}, {"oid": "B"}], {"objects": {"path": "[]", "object_partition": {"mode": "field", "field": "oid"}}})
    for portfolio in portfolios:
        assert portfolio.executions[0].internal_execution_id.value == "execution:test"
        source = portfolio.records[0].internal_source
        assert source.internal_execution_id.value == "execution:test"
        assert source.payload_key == "objects" and source.payload_path == "[]"
        assert source.payload_index in (0, 1)


def test_missing_partition_data_and_ambiguous_arrays_fail(tmp_path):
    with pytest.raises(PortfolioBuildError, match="missing object partition field"):
        _build(tmp_path, [{"ra": 1}], {"objects": {"path": "[]", "object_partition": {"mode": "field", "field": "oid"}}})
    with pytest.raises(PortfolioBuildError, match="no explicit object_partition"):
        _build(tmp_path, [{"oid": "A"}, {"oid": "B"}], {"objects": {"path": "[]"}})


@pytest.mark.parametrize("payload, count_expected", [([], 0), ([{"oid": "A"}], 1), ([{"oid": "A"}, {"oid": "B"}], 2)])
def test_singular_compatibility_wrapper_is_strict(tmp_path, payload, count_expected):
    path = _mapping(tmp_path, {"objects": {"path": "[]", "object_partition": {"mode": "field", "field": "oid"}}})
    if count_expected == 1:
        assert build_portfolio_from_execution(_execution(payload), mappings_path=path).records
    else:
        with pytest.raises(PortfolioBuildError, match="requires exactly one object"):
            build_portfolio_from_execution(_execution(payload), mappings_path=path)
