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
)
from alertissimo.data_layer.runtime.serialization import portfolio_to_dict


def _build(tmp_path, payload, mappings, transforms=None):
    document = {
        "broker": "test",
        "origin": "ztf",
        "payloads": {
            "row": {
                "endpoint": "object",
                "path": "rows[]",
                "object_partition": {"mode": "single"},
            }
        },
        "mappings": mappings,
    }
    if transforms:
        document["transforms"] = transforms
    path = tmp_path / "mappings.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    execution = ExecutionResult(
        payload={"rows": payload},
        execution_provenance=InternalExecutionProvenance(
            internal_execution_id=InternalExecutionId("execution:test"),
            broker="test",
            origin="ztf",
            endpoint="object",
        ),
    )
    ids = count()
    return build_portfolio_from_execution(
        execution,
        mappings_path=path,
        internal_portfolio_id=InternalPortfolioId("portfolio:test"),
        record_id_factory=lambda: InternalRecordId(f"record:{next(ids)}"),
        validate_semantic_model=True,
    )


def test_row_fragments_collect_into_one_points_array(tmp_path):
    mappings = {
        "lightcurve@ztf:test.points.time.mjd": ["row#jd"],
        "lightcurve@ztf:test.points.photometry.{filter}": ["row#fid"],
        "lightcurve@ztf:test.points.photometry.{filter}.psf.mag": ["row#mag"],
    }
    transforms = {
        "lightcurve@ztf:test.points.photometry.{filter}": {
            "row#fid": {"type": "value_map", "map": {1: "g", 2: "r"}}
        }
    }
    portfolio = _build(
        tmp_path,
        [
            {"jd": 1.0, "fid": 1, "mag": 18.1},
            {"jd": 2.0, "fid": 2, "mag": 18.2},
        ],
        mappings,
        transforms,
    )

    assert len(portfolio.records) == 1
    record = portfolio.records[0]
    assert record.semantic_type == "lightcurve@ztf:test"
    assert record.fields["points"] == (
        {"time.mjd": 1.0, "photometry.g.psf.mag": 18.1},
        {"time.mjd": 2.0, "photometry.r.psf.mag": 18.2},
    )
    assert not any(path.startswith("points.") for path in record.fields)
    assert record.internal_source is not None
    assert record.internal_source.payload_key == "row"
    assert record.internal_source.payload_path == "rows[]"
    assert record.internal_source.payload_index is None

    serialized = portfolio_to_dict(portfolio)
    assert serialized["records"][0]["fields"]["points"] == [
        {"time.mjd": 1.0, "photometry.g.psf.mag": 18.1},
        {"time.mjd": 2.0, "photometry.r.psf.mag": 18.2},
    ]


def test_one_row_can_contribute_to_multiple_intrinsic_arrays(tmp_path):
    mappings = {
        "lightcurve@fink.magnitude_rate_points.time.mjd": ["row#mjd"],
        "lightcurve@fink.magnitude_rate_points.photometry.{filter}": ["row#fid"],
        "lightcurve@fink.magnitude_rate_points.photometry.{filter}.mag.rate": ["row#rate"],
        "lightcurve@fink.color_points.time.mjd": ["row#mjd"],
        "lightcurve@fink.color_points.color.g-r.diff": ["row#color"],
    }
    transforms = {
        "lightcurve@fink.magnitude_rate_points.photometry.{filter}": {
            "row#fid": {"type": "value_map", "map": {1: "g", 2: "r"}}
        }
    }
    portfolio = _build(
        tmp_path,
        [
            {"mjd": 10.0, "fid": 1, "rate": -0.2, "color": 0.4},
            {"mjd": 11.0, "fid": 2, "rate": 0.1, "color": 0.5},
        ],
        mappings,
        transforms,
    )

    (record,) = portfolio.records
    assert record.fields["magnitude_rate_points"] == (
        {"time.mjd": 10.0, "photometry.g.mag.rate": -0.2},
        {"time.mjd": 11.0, "photometry.r.mag.rate": 0.1},
    )
    assert record.fields["color_points"] == (
        {"time.mjd": 10.0, "color.g-r.diff": 0.4},
        {"time.mjd": 11.0, "color.g-r.diff": 0.5},
    )


def test_context_only_derived_points_are_pruned(tmp_path):
    mappings = {
        "lightcurve@fink.magnitude_rate_points.time.mjd": ["row#mjd"],
        "lightcurve@fink.magnitude_rate_points.identity.source_id": ["row#source"],
        "lightcurve@fink.magnitude_rate_points.photometry.g.mag.rate": ["row#rate"],
        "lightcurve@fink.color_points.time.mjd": ["row#mjd"],
        "lightcurve@fink.color_points.identity.source_id": ["row#source"],
        "lightcurve@fink.color_points.color.g-r.diff": ["row#color"],
    }
    portfolio = _build(
        tmp_path,
        [
            {"mjd": 10.0, "source": "a"},
            {"mjd": 11.0, "source": "b", "rate": 0.1, "color": 0.5},
        ],
        mappings,
    )

    (record,) = portfolio.records
    assert record.fields["magnitude_rate_points"] == (
        {"time.mjd": 11.0, "identity.source_id": "b", "photometry.g.mag.rate": 0.1},
    )
    assert record.fields["color_points"] == (
        {"time.mjd": 11.0, "identity.source_id": "b", "color.g-r.diff": 0.5},
    )


def test_json_feature_vectors_decode_skip_empty_and_collect(tmp_path):
    mappings = {
        "lightcurve@fink.feature_vector_points.time.mjd": ["row#jd"],
        "lightcurve@fink.feature_vector_points.identity.source_id": ["row#source"],
        "lightcurve@fink.feature_vector_points.g.value": ["row#g"],
        "lightcurve@fink.feature_vector_points.r.value": ["row#r"],
    }
    transforms = {
        "lightcurve@fink.feature_vector_points.time.mjd": {
            "row#jd": {"type": "jd_to_mjd"}
        },
        "lightcurve@fink.feature_vector_points.g.value": {
            "row#g": {"type": "json_decode", "skip_empty": True}
        },
        "lightcurve@fink.feature_vector_points.r.value": {
            "row#r": {"type": "json_decode", "skip_empty": True}
        },
    }
    portfolio = _build(
        tmp_path,
        [
            {"jd": 2400010.5, "source": "a", "g": "[]", "r": "[]"},
            {"jd": 2400011.5, "source": "b", "g": "[1.0, 2.0]", "r": "[]"},
        ],
        mappings,
        transforms,
    )

    (record,) = portfolio.records
    assert record.fields["feature_vector_points"] == (
        {"time.mjd": 11.0, "identity.source_id": "b", "g.value": [1.0, 2.0]},
    )


def test_root_lightcurve_fields_deduplicate_while_points_collect(tmp_path):
    mappings = {
        "lightcurve@fink.detection_count": ["row#count"],
        "lightcurve@fink.magnitude_rate_points.time.mjd": ["row#mjd"],
        "lightcurve@fink.magnitude_rate_points.photometry.g.mag.rate": ["row#rate"],
    }
    portfolio = _build(
        tmp_path,
        [
            {"count": 2, "mjd": 10.0, "rate": -0.2},
            {"count": 2, "mjd": 11.0, "rate": 0.1},
        ],
        mappings,
    )
    (record,) = portfolio.records
    assert record.fields["detection_count"] == 2
    assert len(record.fields["magnitude_rate_points"]) == 2


def test_conflicting_root_values_fail_instead_of_silently_overwriting(tmp_path):
    mappings = {
        "lightcurve@fink.detection_count": ["row#count"],
        "lightcurve@fink.magnitude_rate_points.time.mjd": ["row#mjd"],
        "lightcurve@fink.magnitude_rate_points.photometry.g.mag.rate": ["row#rate"],
    }
    with pytest.raises(PortfolioBuildError, match="conflicting root values"):
        _build(
            tmp_path,
            [
                {"count": 2, "mjd": 10.0, "rate": -0.2},
                {"count": 3, "mjd": 11.0, "rate": 0.1},
            ],
            mappings,
        )


def test_non_lightcurve_records_keep_row_cardinality(tmp_path):
    mappings = {
        "detection@ztf:test.time.mjd": ["row#jd"],
        "lightcurve@ztf:test.points.time.mjd": ["row#jd"],
        "lightcurve@ztf:test.points.photometry.g.psf.mag": ["row#mag"],
    }
    portfolio = _build(
        tmp_path,
        [{"jd": 1.0, "mag": 18.1}, {"jd": 2.0, "mag": 18.2}],
        mappings,
    )
    detections = [
        record for record in portfolio.records if record.semantic_type == "detection@ztf:test"
    ]
    lightcurves = [
        record for record in portfolio.records if record.semantic_type == "lightcurve@ztf:test"
    ]
    assert [record.fields["time.mjd"] for record in detections] == [1.0, 2.0]
    assert [record.internal_source.payload_index for record in detections] == [0, 1]
    assert len(lightcurves) == 1
    assert lightcurves[0].fields["points"] == (
        {"time.mjd": 1.0, "photometry.g.psf.mag": 18.1},
        {"time.mjd": 2.0, "photometry.g.psf.mag": 18.2},
    )
