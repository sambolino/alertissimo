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
from alertissimo.data_layer.runtime.record_builder import PortfolioBuildError, build_portfolio_from_execution


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


@pytest.mark.parametrize(("raw", "expected"), [
    (None, None), (" abc ", "abc"), (123, "123"), (12.5, "12.5"),
])
def test_to_string_strip_converts_scalars(tmp_path, raw, expected):
    portfolio = _build_with_transform(tmp_path, raw, {"type": "to_string_strip"})
    assert portfolio.records[0].fields["value"] == expected


@pytest.mark.parametrize(("raw", "expected"), [
    (None, None), ("12.3", 12.3), (12, 12.0), (12.3, 12.3),
])
def test_to_float_converts_numeric_values(tmp_path, raw, expected):
    portfolio = _build_with_transform(tmp_path, raw, {"type": "to_float"})
    assert portfolio.records[0].fields["value"] == expected


def test_to_float_rejects_invalid_values(tmp_path):
    with pytest.raises(ValueError, match="cannot convert 'abc' to float"):
        _build_with_transform(tmp_path, "abc", {"type": "to_float"})


@pytest.mark.parametrize(("raw", "expected"), [
    (None, None), (1, 1), ("2", 2), (3.0, 3), ("4.0", 4),
])
def test_to_int_converts_only_integral_values(tmp_path, raw, expected):
    portfolio = _build_with_transform(tmp_path, raw, {"type": "to_int"})
    assert portfolio.records[0].fields["value"] == expected


@pytest.mark.parametrize("raw", [1.5, "2.5", "abc"])
def test_to_int_rejects_non_integral_values(tmp_path, raw):
    with pytest.raises(ValueError, match="cannot convert"):
        _build_with_transform(tmp_path, raw, {"type": "to_int"})


@pytest.mark.parametrize(("specification", "expected"), [
    ({"type": "value_map", "map": {"A": "star"}, "default": "unknown"}, "unknown"),
    ({"type": "value_map", "map": {"A": "star"}}, "B"),
])
def test_value_map_optional_default(tmp_path, specification, expected):
    portfolio = _build_with_transform(tmp_path, "B", specification)
    assert portfolio.records[0].fields["value"] == expected


@pytest.mark.parametrize("specification", [
    {"type": "to_float"}, {"type": "to_float", "skip_null": False},
])
def test_null_is_preserved_without_enabled_skip_null(tmp_path, specification):
    portfolio = _build_with_transform(tmp_path, None, specification)
    assert portfolio.records[0].fields["value"] is None


@pytest.mark.parametrize("specification", [
    {"type": "to_float", "skip_null": True}, {"skip_null": True},
])
def test_skip_null_omits_null_field(tmp_path, specification):
    portfolio = _build_with_transform(tmp_path, None, specification)
    assert portfolio.records == ()


def _build_with_transform(tmp_path, raw, specification):
    semantic_path = "object@ztf:lasair.value"
    return _build(tmp_path, {"raw": raw}, {
        "broker": "lasair", "origin": "ztf",
        "payloads": {"object": {"path": "."}},
        "mappings": {semantic_path: ["object#raw"]},
        "transforms": {semantic_path: {"object#raw": specification}},
    })


def test_discovers_mapping_from_execution_provenance(tmp_path):
    root = tmp_path / "providers"
    path = root / "lasair" / "ztf" / "mappings.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump({
        "broker": "lasair", "origin": "ztf",
        "payloads": {"object": {"path": "."}},
        "mappings": {"summary@ztf:lasair.identity.object_id": ["object#objectId"]},
    }), encoding="utf-8")
    portfolio = build_portfolio_from_execution(_execution({"objectId": "ZTF-test"}), providers_root=root)
    assert portfolio.records[0].fields["identity.object_id"] == "ZTF-test"


def test_missing_discovered_mapping_has_builder_error(tmp_path):
    with pytest.raises(PortfolioBuildError, match="cannot resolve mappings.yaml for lasair/ztf"):
        build_portfolio_from_execution(_execution({}), providers_root=tmp_path)


def _dynamic_mapping():
    return {
        "broker": "lasair", "origin": "ztf",
        "payloads": {"candidate": {"endpoint": "object", "path": "candidates[]"}},
        "mappings": {
            "detection@ztf:lasair.photometry.{filter}": ["candidate#fid"],
            "detection@ztf:lasair.photometry.{filter}.psf.mag": ["candidate#magpsf"],
            "detection@ztf:lasair.photometry.{filter}.psf.mag_error": ["candidate#sigmapsf"],
        },
        "transforms": {
            "detection@ztf:lasair.photometry.{filter}": {
                "candidate#fid": {"type": "value_map", "map": {1: "g", 2: "r", 3: "i"}}
            }
        },
    }


def test_dynamic_filter_binds_sibling_field_paths(tmp_path):
    portfolio = _build(tmp_path, {
        "candidates": [{"fid": 1, "magpsf": 18.2, "sigmapsf": 0.1}]
    }, _dynamic_mapping())
    fields = dict(portfolio.records[0].fields)
    assert fields == {
        "photometry.g.psf.mag": 18.2,
        "photometry.g.psf.mag_error": 0.1,
    }
    assert "photometry.{filter}" not in fields
    assert "photometry.{filter}.psf.mag" not in fields


def test_unresolved_semantic_type_producer_falls_back_to_unknown(tmp_path):
    portfolio = _build(
        tmp_path,
        {"sherlock": {"catalogue_object_id": "WISEA J081336.12+221200.3"}},
        {
            "broker": "lasair",
            "origin": "ztf",
            "payloads": {"object": {"endpoint": "object", "path": "."}},
            "mappings": {
                "crossmatch@{producer}:lasair.identity.object_id": [
                    "object#sherlock.catalogue_object_id"
                ],
            },
        },
    )

    semantic_types = [record.semantic_type for record in portfolio.records]
    assert semantic_types == ["crossmatch@unknown:lasair"]
    assert "crossmatch@{producer}:lasair" not in semantic_types
    assert "crossmatch@sherlock:lasair" not in semantic_types
    assert dict(portfolio.records[0].fields) == {
        "identity.object_id": "WISEA J081336.12+221200.3"
    }


def test_semantic_type_producer_uses_dynamic_field_binding(tmp_path):
    portfolio = _build(
        tmp_path,
        {"catalogue": "gaia", "source_id": "123"},
        {
            "broker": "lasair",
            "origin": "ztf",
            "payloads": {"object": {"endpoint": "object", "path": "."}},
            "mappings": {
                "crossmatch@{producer}:lasair.identity.{producer}": [
                    "object#catalogue"
                ],
                "crossmatch@{producer}:lasair.identity.object_id": [
                    "object#source_id"
                ],
            },
        },
    )

    assert [record.semantic_type for record in portfolio.records] == [
        "crossmatch@gaia:lasair"
    ]
    assert dict(portfolio.records[0].fields) == {"identity.object_id": "123"}


def test_dynamic_filter_binding_is_scoped_to_each_payload_item(tmp_path):
    portfolio = _build(tmp_path, {"candidates": [
        {"fid": 1, "magpsf": 18.2},
        {"fid": 2, "magpsf": 18.7},
    ]}, _dynamic_mapping())
    assert [dict(record.fields) for record in portfolio.records] == [
        {"photometry.g.psf.mag": 18.2},
        {"photometry.r.psf.mag": 18.7},
    ]


def test_missing_dynamic_binder_leaves_placeholder_inspectable(tmp_path):
    portfolio = _build(
        tmp_path, {"candidates": [{"magpsf": 18.2}]}, _dynamic_mapping()
    )
    assert dict(portfolio.records[0].fields) == {
        "photometry.{filter}.psf.mag": 18.2
    }


def test_conflicting_dynamic_binders_raise_builder_error(tmp_path):
    mapping = _dynamic_mapping()
    mapping["mappings"]["detection@ztf:lasair.calibration.{filter}"] = ["candidate#other_fid"]
    mapping["transforms"]["detection@ztf:lasair.calibration.{filter}"] = {
        "candidate#other_fid": {"type": "value_map", "map": {2: "r"}}
    }
    with pytest.raises(
        PortfolioBuildError,
        match=r"conflicting binding for placeholder \{filter\}: g vs r",
    ):
        _build(tmp_path, {"candidates": [{"fid": 1, "other_fid": 2}]}, mapping)
