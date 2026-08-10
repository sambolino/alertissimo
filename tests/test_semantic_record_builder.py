from itertools import count

import yaml

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
    InternalPortfolioId,
    InternalRecordId,
)
from alertissimo.data_layer.runtime.record_builder import build_portfolio_from_execution


def _execution(payload):
    provenance = InternalExecutionProvenance(
        internal_execution_id=InternalExecutionId("execution:test"),
        broker="lasair",
        origin="ztf",
        endpoint="object",
    )
    return ExecutionResult(payload=payload, execution_provenance=provenance)


def _build(tmp_path, payload, document):
    path = tmp_path / "mappings.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    ids = count()
    return build_portfolio_from_execution(
        _execution(payload),
        mappings_path=path,
        internal_portfolio_id=InternalPortfolioId("portfolio:test"),
        record_id_factory=lambda: InternalRecordId(f"record:{next(ids)}"),
    )


def test_root_object_builds_one_record_with_relative_fields(tmp_path):
    portfolio = _build(tmp_path, {"objectId": "ZTF25aazqavg", "ra": 123.4, "dec": 22.2}, {
        "broker": "lasair", "origin": "ztf",
        "payloads": {"object": {"endpoint": "object", "path": "."}},
        "mappings": {
            "detection@ztf:lasair.identity.source_id": ["object#objectId"],
            "detection@ztf:lasair.position.ra": ["object#ra"],
            "detection@ztf:lasair.position.dec": ["object#dec"],
        },
    })
    assert len(portfolio.records) == 1
    record = portfolio.records[0]
    assert record.semantic_type == "detection@ztf:lasair"
    assert dict(record.fields) == {
        "identity.source_id": "ZTF25aazqavg", "position.ra": 123.4, "position.dec": 22.2,
    }
    assert all("@" not in key for key in record.fields)
    assert record.internal_source.payload_key == "object"
    assert record.internal_source.payload_path == "."
    assert record.internal_source.payload_index is None
    assert len(portfolio.executions) == 1


def test_list_payload_builds_one_record_per_item(tmp_path):
    portfolio = _build(tmp_path, {"candidates": [
        {"candid": 1, "magpsf": 18.2}, {"candid": 2, "magpsf": 18.5},
    ]}, {
        "broker": "lasair", "origin": "ztf",
        "payloads": {"candidate": {"endpoint": "object", "path": "candidates[]"}},
        "mappings": {
            "detection@ztf:lasair.identity.source_id": ["candidate#candid"],
            "detection@ztf:lasair.photometry.mag": ["candidate#magpsf"],
        },
    })
    assert [record.internal_source.payload_index for record in portfolio.records] == [0, 1]
    assert [dict(record.fields) for record in portfolio.records] == [
        {"identity.source_id": 1, "photometry.mag": 18.2},
        {"identity.source_id": 2, "photometry.mag": 18.5},
    ]
    assert len(portfolio.executions) == 1


def test_jd_transform_and_missing_fields(tmp_path):
    portfolio = _build(tmp_path, {"candidates": [{"jd": 2460000.5}]}, {
        "broker": "lasair", "origin": "ztf",
        "payloads": {"candidate": {"endpoint": "object", "path": "candidates[]"}},
        "mappings": {
            "detection@ztf:lasair.time.mjd": ["candidate#jd"],
            "detection@ztf:lasair.position.ra": ["candidate#ra"],
            "object@ztf:lasair.identity.source_id": ["candidate#missing"],
        },
        "transforms": {"detection@ztf:lasair.time.mjd": {
            "candidate#jd": {"type": "jd_to_mjd"},
        }},
    })
    assert len(portfolio.records) == 1
    assert dict(portfolio.records[0].fields) == {"time.mjd": 60000.0}


def test_boolean_not_and_value_map(tmp_path):
    portfolio = _build(tmp_path, {"rows": [{"flag": 0, "code": "A"}]}, {
        "broker": "lasair", "origin": "ztf",
        "payloads": {"row": {"path": "rows[]"}},
        "mappings": {
            "object@ztf:lasair.flags.active": ["row#flag"],
            "object@ztf:lasair.classification.label": ["row#code"],
        },
        "transforms": {
            "object@ztf:lasair.flags.active": {"row#flag": {"type": "boolean_not"}},
            "object@ztf:lasair.classification.label": {
                "row#code": {"type": "value_map", "map": {"A": "star"}}
            },
        },
    })
    assert dict(portfolio.records[0].fields) == {
        "flags.active": True, "classification.label": "star",
    }
