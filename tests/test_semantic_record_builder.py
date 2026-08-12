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


def _transform_document(transform, references=None):
    semantic_path = "object@ztf:lasair.value"
    references = references or ["object#value"]
    return {
        "broker": "lasair",
        "origin": "ztf",
        "payloads": {"object": {"path": "."}},
        "mappings": {semantic_path: references},
        "transforms": {semantic_path: transform},
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), (" abc ", "abc"), (123, "123"), (12.5, "12.5")],
)
def test_to_string_strip_strips_strings_and_converts_scalars(
    tmp_path, value, expected
):
    document = _transform_document(
        {"object#value": {"type": "to_string_strip"}}
    )
    portfolio = _build(tmp_path, {"value": value}, document)
    assert portfolio.records[0].fields["value"] == expected


@pytest.mark.parametrize(
    ("value", "expected"), [(None, None), ("12.3", 12.3), (12, 12.0), (12.3, 12.3)]
)
def test_to_float_converts_numeric_strings_and_numbers(tmp_path, value, expected):
    document = _transform_document({"object#value": {"type": "to_float"}})
    portfolio = _build(tmp_path, {"value": value}, document)
    assert portfolio.records[0].fields["value"] == expected


def test_to_float_rejects_invalid_values(tmp_path):
    document = _transform_document({"object#value": {"type": "to_float"}})
    with pytest.raises(ValueError, match="cannot convert 'abc' to float"):
        _build(tmp_path, {"value": "abc"}, document)


@pytest.mark.parametrize(
    ("value", "expected"), [(None, None), (1, 1), ("2", 2), (3.0, 3), ("4.0", 4)]
)
def test_to_int_converts_integral_values_only(tmp_path, value, expected):
    document = _transform_document({"object#value": {"type": "to_int"}})
    portfolio = _build(tmp_path, {"value": value}, document)
    assert portfolio.records[0].fields["value"] == expected


@pytest.mark.parametrize("value", [1.5, "2.5", "abc"])
def test_to_int_rejects_non_integral_values(tmp_path, value):
    document = _transform_document({"object#value": {"type": "to_int"}})
    with pytest.raises(ValueError, match="cannot convert"):
        _build(tmp_path, {"value": value}, document)


@pytest.mark.parametrize(("value", "expected"), [(None, None), (2, 7200), (0.5, 1800.0)])
def test_scale_multiplies_numeric_values_without_coercion(tmp_path, value, expected):
    document = _transform_document(
        {"object#value": {"type": "scale", "factor": 3600}}
    )
    portfolio = _build(tmp_path, {"value": value}, document)
    assert portfolio.records[0].fields["value"] == expected


def test_scale_does_not_coerce_strings(tmp_path):
    document = _transform_document(
        {"object#value": {"type": "scale", "factor": 2}}
    )
    with pytest.raises(TypeError, match="cannot scale non-numeric value"):
        _build(tmp_path, {"value": "2"}, document)


def test_value_map_default_maps_unknown_to_default(tmp_path):
    document = _transform_document(
        {"object#value": {"type": "value_map", "map": {"A": "star"}, "default": "unknown"}}
    )
    portfolio = _build(tmp_path, {"value": "B"}, document)
    assert portfolio.records[0].fields["value"] == "unknown"


def test_value_map_without_default_preserves_old_behavior(tmp_path):
    document = _transform_document(
        {"object#value": {"type": "value_map", "map": {"A": "star"}}}
    )
    portfolio = _build(tmp_path, {"value": "B"}, document)
    assert portfolio.records[0].fields["value"] == "B"


def test_skip_null_omits_null_field_when_no_fallback_exists(tmp_path):
    document = _transform_document(
        {"object#value": {"type": "to_float", "skip_null": True}}
    )
    portfolio = _build(tmp_path, {"value": None}, document)
    assert portfolio.records == ()


def test_skip_null_precedes_jd_arithmetic_and_preserves_real_transform(tmp_path):
    path = "detection@ztf:lasair.time.mjd"
    document = {
        "broker": "lasair", "origin": "ztf",
        "payloads": {"object": {"path": "."}},
        "mappings": {path: ["object#value"]},
        "transforms": {path: {"object#value": {
            "type": "jd_to_mjd", "skip_null": True,
        }}},
    }
    assert _build(tmp_path, {"value": None}, document).records == ()
    portfolio = _build(tmp_path, {"value": 2459396.7497338}, document)
    assert portfolio.records[0].fields["time.mjd"] == pytest.approx(59396.2497338)

    without_skip = dict(document)
    without_skip["transforms"] = {path: {"object#value": {"type": "jd_to_mjd"}}}
    with pytest.raises(TypeError):
        _build(tmp_path, {"value": None}, without_skip)


def test_skip_null_continues_to_fallback_reference(tmp_path):
    document = _transform_document(
        {
            "object#primary": {"type": "to_float", "skip_null": True},
            "object#fallback": {"type": "to_float"},
        },
        ["object#primary", "object#fallback"],
    )
    portfolio = _build(tmp_path, {"primary": None, "fallback": "2.5"}, document)
    assert portfolio.records[0].fields["value"] == 2.5


def test_skip_null_only_specification_does_not_require_type(tmp_path):
    document = _transform_document({"object#value": {"skip_null": True}})
    portfolio = _build(tmp_path, {"value": "present"}, document)
    assert portfolio.records[0].fields["value"] == "present"


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
            "detection@ztf:lasair.photometry.{filter}.psf.mag.error": ["candidate#sigmapsf"],
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
        "photometry.g.psf.mag.error": 0.1,
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


def test_semantic_type_producer_uses_stable_provenance_field(tmp_path):
    portfolio = _build(
        tmp_path,
        {"catalogue_id": "gaia", "catalogue_name": "Gaia DR3", "source_id": "123"},
        {
            "broker": "lasair",
            "origin": "ztf",
            "payloads": {"object": {"endpoint": "object", "path": "."}},
            "mappings": {
                "crossmatch@{producer}:lasair.provenance.producer.id": [
                    "object#catalogue_id"
                ],
                "crossmatch@{producer}:lasair.provenance.producer.name": [
                    "object#catalogue_name"
                ],
                "crossmatch@{producer}:lasair.identity.object_id": [
                    "object#source_id"
                ],
            },
        },
    )

    record = portfolio.records[0]
    fields = dict(record.fields)
    assert record.semantic_type == "crossmatch@gaia:lasair"
    assert fields["provenance.producer.id"] == "gaia"
    assert fields["provenance.producer.name"] == "Gaia DR3"
    assert not {
        "identity.gaia",
        "identity.{producer}",
        "provenance.producer.gaia",
        "provenance.producer.{producer}",
    } & fields.keys()


def test_dynamic_filter_binding_is_scoped_to_each_payload_item(tmp_path):
    portfolio = _build(tmp_path, {"candidates": [
        {"fid": 1, "magpsf": 18.2},
        {"fid": 2, "magpsf": 18.7},
    ]}, _dynamic_mapping())
    assert [dict(record.fields) for record in portfolio.records] == [
        {"photometry.g.psf.mag": 18.2},
        {"photometry.r.psf.mag": 18.7},
    ]


def test_missing_dynamic_binder_omits_dependent_fields(tmp_path):
    portfolio = _build(
        tmp_path, {"candidates": [{"magpsf": 18.2}]}, _dynamic_mapping()
    )
    assert portfolio.records == ()


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
