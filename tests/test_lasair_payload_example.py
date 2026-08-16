import json
import subprocess
import sys
from pathlib import Path

import pytest

from examples.build_lasair_portfolio_from_payload import (
    build_portfolio_from_payload,
    build_portfolios_from_payload,
)
from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance
from alertissimo.data_layer.runtime.record_builder import build_portfolio_from_execution


def _payload():
    return {
        "objectId": "ZTF25realistic",
        "objectData": {
            "ncand": 3,
            "jdmin": 2460000.5,
            "jdmax": 2460002.5,
            "ramean": 123.4,
            "decmean": 22.2,
        },
        "candidates": [
            {"candid": 101, "jd": 2460000.5, "ra": 123.4, "dec": 22.2, "magpsf": 18.2, "sigmapsf": 0.08, "fid": 1},
            {"candid": 102, "jd": 2460001.5, "ra": 123.4, "dec": 22.2, "magpsf": 18.4, "sigmapsf": 0.09, "fid": 2},
            {"candid": 103, "jd": 2460002.5, "ra": 123.4, "dec": 22.2, "magpsf": 18.6, "sigmapsf": 0.10, "fid": 1},
        ],
        "sherlock": {
            "classification": "AGN",
            "classificationReliability": 0.86,
            "catalogue_object_id": "WISEA J081336.12+221200.3",
            "raDeg": 123.401,
            "decDeg": 22.201,
            "separationArcsec": 0.7,
        },
        "TNS": {"name": "AT2026abc", "type": "SN Ia?", "ra": 123.405, "decl": 22.205, "z": 0.043},
    }


def test_build_portfolio_from_saved_lasair_payload():
    portfolio = build_portfolio_from_payload(_payload())
    semantic_types = {record.semantic_type for record in portfolio.records}

    assert "summary@ztf:lasair" in semantic_types
    assert "detection@ztf:lasair" in semantic_types
    assert "classification@sherlock:lasair" in semantic_types
    assert "crossmatch@unknown:lasair" in semantic_types
    assert "crossmatch@{producer}:lasair" not in semantic_types
    assert "crossmatch@sherlock:lasair" not in semantic_types
    assert portfolio.edges == ()
    assert sum(record.semantic_type == "detection@ztf:lasair" for record in portfolio.records) == 3
    assert portfolio.executions[0].params == {"objectId": "ZTF25realistic"}


def test_plural_payload_helper_preserves_strict_singular_compatibility():
    portfolios = build_portfolios_from_payload(_payload())
    assert len(portfolios) == 1
    assert portfolios[0].records


def test_singular_payload_helper_rejects_zero_portfolios():
    with pytest.raises(ValueError, match="normalization produced 0"):
        build_portfolio_from_payload(
            {"classifications": [], "crossmatches": []},
            endpoint="sherlock_position",
        )


def test_compact_object_sherlock_binds_crossmatch_producer():
    payload = _payload()
    payload["sherlock"]["catalogue_table_name"] = "Gaia DR3"

    portfolio = build_portfolio_from_payload(payload)
    crossmatches = [
        record for record in portfolio.records
        if record.semantic_type.startswith("crossmatch@")
        and record.semantic_type != "crossmatch@tns:lasair"
    ]

    assert len(crossmatches) == 1
    assert crossmatches[0].semantic_type == "crossmatch@gaia:lasair"
    assert dict(crossmatches[0].fields)["provenance.producer.id"] == "gaia"
    assert dict(crossmatches[0].fields)["provenance.producer.name"] == "Gaia DR3"


def test_payload_script_reads_file_and_reports_summary(tmp_path):
    payload_path = tmp_path / "object.json"
    payload_path.write_text(json.dumps(_payload()), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "examples/build_lasair_portfolio_from_payload.py",
            str(payload_path),
            "--summary",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    portfolio = json.loads(result.stdout)
    assert len(portfolio["edges"]) == 0
    assert len([record for record in portfolio["records"] if record["semantic_type"] == "detection@ztf:lasair"]) == 3
    assert "payload keys:" in result.stderr
    assert "endpoint: object" in result.stderr
    assert "records built:" in result.stderr
    assert "edges built: 0" in result.stderr


def test_payload_script_rejects_non_object_json(tmp_path):
    payload_path = tmp_path / "array.json"
    payload_path.write_text("[]", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "examples/build_lasair_portfolio_from_payload.py", str(payload_path)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "must be a JSON object" in result.stderr


def test_payload_script_reports_endpoint_and_zero_record_diagnostic(tmp_path):
    payload_path = tmp_path / "sherlock_position.json"
    payload_path.write_text(json.dumps({"classifications": [], "crossmatches": []}), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "examples/build_lasair_portfolio_from_payload.py",
            str(payload_path),
            "--endpoint",
            "sherlock_position",
            "--summary",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "endpoint: sherlock_position" in result.stderr
    assert "payload keys: classifications, crossmatches" in result.stderr
    assert "records built: 0" in result.stderr
    assert "portfolios built: 0" in result.stderr
    assert "No semantic records were built for this endpoint/payload shape." in result.stderr
    assert json.loads(result.stdout) == []


def test_sherlock_position_classification_dictionary():
    description = (
        'The transient is synonymous with <a href="http://skyserver.sdss.org/dr12/'
        'en/tools/explore/summary.aspx?id=1237661972796145844">'
        'SDSS J122001.74+082413.4</a>; a G=19.91 mag AGN.'
    )
    portfolio = build_portfolio_from_payload(
        {
            "classifications": {
                "170028526577123339": ["AGN", description]
            }
        },
        endpoint="sherlock_position",
    )

    records = [
        record
        for record in portfolio.records
        if record.semantic_type == "classification@sherlock:lasair"
    ]
    assert len(records) == 1
    fields = dict(records[0].fields)
    assert fields["best.class"] == "AGN"
    assert fields["best.description"] == description
    assert "identity.object_id" not in fields
    assert "subject.object_id" not in fields
    assert "target.object_id" not in fields
    assert portfolio.edges == ()


def test_observed_ztf_sherlock_position_preserves_scientific_roles():
    path = Path("tests/fixtures/lasair/ztf/sherlock_position.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    portfolio = _build_endpoint_payload(payload, "sherlock_position")
    classifications = [r for r in portfolio.records if r.semantic_type == "classification@sherlock:lasair"]
    crossmatches = [r for r in portfolio.records if r.semantic_type.startswith("crossmatch@")]
    assert len(classifications) == 1
    assert len(crossmatches) == 4
    classification = dict(classifications[0].fields)
    assert classification == {
        "best.class": "SN",
        "best.description": payload["classifications"]["ZTF20acpwljl"][1],
    }
    records = {r.semantic_type: dict(r.fields) for r in crossmatches}
    combined = records["crossmatch@sdss_2mass_ps1:lasair"]
    assert combined["classification.assessment.catalogue.class"] == "galaxy"
    assert combined["classification.assessment.sherlock.class"] == "SN"
    assert combined["classification.assessment.sherlock.score"] == 2.0
    assert combined["classification.assessment.sherlock.method"] == "multiple"
    assert "redshift.value" not in combined
    assert "redshift.error" not in combined
    assert combined["separation.north"] == -1.15164
    assert combined["separation.east"] == 1.06992
    assert combined["photometry.J.mag"] == 17.007
    twomass = records["crossmatch@twomass:lasair"]
    assert twomass["identity.object_id"] == "08193126-0601149"
    assert twomass["classification.assessment.catalogue.class"] == "star"
    assert twomass["classification.assessment.sherlock.class"] == "VS"
    assert twomass["classification.assessment.sherlock.score"] == 2.0
    assert twomass["classification.assessment.sherlock.method"] == "2mass star angular"
    assert records["crossmatch@panstarrs:lasair"]["classification.assessment.sherlock.method"] == "ps1 galaxy r angular"
    assert records["crossmatch@sdss:lasair"]["classification.assessment.sherlock.method"] == "sdss phot galaxy angular"
    assert portfolio.edges == ()


def test_sherlock_objects_classification_dictionary():
    description = (
        'The transient is synonymous with <a href="http://skyserver.sdss.org/dr12/'
        'en/tools/explore/summary.aspx?id=1237661972796145844">'
        'SDSS J122001.74+082413.4</a>; a G=19.91 mag AGN.'
    )
    provenance = InternalExecutionProvenance(
        internal_execution_id=InternalExecutionId("execution:test:sherlock-objects"),
        broker="lasair",
        origin="ztf",
        endpoint="sherlock_objects",
    )
    portfolio = build_portfolio_from_execution(
        ExecutionResult(
            payload={
                "classifications": {
                    "170028526577123339": ["AGN", description]
                }
            },
            execution_provenance=provenance,
        ),
        validate_semantic_model=True,
    )

    records = [
        record
        for record in portfolio.records
        if record.semantic_type == "classification@sherlock:lasair"
    ]
    assert len(records) == 1
    fields = dict(records[0].fields)
    assert fields["best.class"] == "AGN"
    assert fields["best.description"] == description
    assert "identity.object_id" not in fields
    assert "subject.object_id" not in fields
    assert "target.object_id" not in fields
    assert portfolio.edges == ()


def _build_endpoint_payload(payload, endpoint):
    provenance = InternalExecutionProvenance(
        internal_execution_id=InternalExecutionId(f"execution:test:{endpoint}"),
        broker="lasair",
        origin="ztf",
        endpoint=endpoint,
    )
    return build_portfolio_from_execution(
        ExecutionResult(payload=payload, execution_provenance=provenance),
        validate_semantic_model=True,
    )


def test_sherlock_crossmatch_observed_producers_normalize():
    payload = {
        "crossmatches": [
            {
                "catalogue_table_name": "SDSS/2MASS/PS1",
                "catalogue_table_id": 1,
                "catalogue_object_id": "1237673709862061782",
            },
            {
                "catalogue_table_name": "2MASS PSC",
                "catalogue_table_id": 2,
                "catalogue_object_id": "08193126-0601149 ",
            },
            {
                "catalogue_table_name": "PanSTARRS DR1",
                "catalogue_table_id": 3,
                "catalogue_object_id": 100771248804585479,
            },
            {
                "catalogue_table_name": "SDSS DR12 PhotoObjAll Table",
                "catalogue_table_id": 4,
                "catalogue_object_id": "123",
            },
        ]
    }
    portfolio = _build_endpoint_payload(payload, "sherlock_position")
    records = [
        record
        for record in portfolio.records
        if record.semantic_type.startswith("crossmatch@")
    ]
    semantic_types = {record.semantic_type for record in records}

    assert semantic_types == {
        "crossmatch@sdss_2mass_ps1:lasair",
        "crossmatch@twomass:lasair",
        "crossmatch@panstarrs:lasair",
        "crossmatch@sdss:lasair",
    }
    assert "crossmatch@sherlock:lasair" not in semantic_types
    assert "crossmatch@{producer}:lasair" not in semantic_types
    assert "crossmatch@unknown:lasair" not in semantic_types
    fields = {record.semantic_type: dict(record.fields) for record in records}
    assert fields["crossmatch@sdss_2mass_ps1:lasair"] == {
        "identity.object_id": "1237673709862061782",
        "provenance.producer.name": "SDSS/2MASS/PS1",
        "provenance.producer.id": "sdss_2mass_ps1",
    }
    assert (
        fields["crossmatch@twomass:lasair"]["identity.object_id"] == "08193126-0601149"
    )
    assert (
        fields["crossmatch@panstarrs:lasair"]["identity.object_id"]
        == "100771248804585479"
    )
    assert portfolio.edges == ()


def test_sherlock_objects_crossmatch_object_response_shape():
    portfolio = _build_endpoint_payload(
        {
            "crossmatches": [
                {
                    "catalogue_table_name": "2MASS PSC",
                    "catalogue_table_id": 2,
                    "catalogue_object_id": "abc",
                }
            ]
        },
        "sherlock_objects",
    )

    records = [
        record
        for record in portfolio.records
        if record.semantic_type == "crossmatch@twomass:lasair"
    ]
    assert len(records) == 1
    assert portfolio.edges == ()


def test_sherlock_crossmatch_new_producer_aliases_normalize():
    names = [
        "SDSS/MILLIQUAS/GAIA/DESI/PS1",
        "Million Quasars (MILLIQUAS) Catalog v8.0",
        "Gaia DR3",
        "DESI Legacy Survey DR10",
    ]
    portfolio = _build_endpoint_payload(
        {
            "crossmatches": [
                {"catalogue_table_name": name, "catalogue_object_id": str(index)}
                for index, name in enumerate(names)
            ]
        },
        "sherlock_position",
    )

    assert {record.semantic_type for record in portfolio.records} == {
        "crossmatch@sdss_milliquas_gaia_desi_ps1:lasair",
        "crossmatch@milliquas:lasair",
        "crossmatch@gaia:lasair",
        "crossmatch@desi_legacy_survey:lasair",
    }
    records = {
        record.semantic_type: dict(record.fields)
        for record in portfolio.records
    }

    combined_fields = records["crossmatch@sdss_milliquas_gaia_desi_ps1:lasair"]
    assert (
        combined_fields["provenance.producer.id"]
        == "sdss_milliquas_gaia_desi_ps1"
    )
    assert (
        combined_fields["provenance.producer.name"]
        == "SDSS/MILLIQUAS/GAIA/DESI/PS1"
    )

    milliquas_fields = records["crossmatch@milliquas:lasair"]
    assert milliquas_fields["provenance.producer.id"] == "milliquas"
    assert (
        milliquas_fields["provenance.producer.name"]
        == "Million Quasars (MILLIQUAS) Catalog v8.0"
    )

    gaia_fields = records["crossmatch@gaia:lasair"]
    assert gaia_fields["provenance.producer.id"] == "gaia"
    assert gaia_fields["provenance.producer.name"] == "Gaia DR3"

    desi_fields = records["crossmatch@desi_legacy_survey:lasair"]
    assert desi_fields["provenance.producer.id"] == "desi_legacy_survey"
    assert desi_fields["provenance.producer.name"] == "DESI Legacy Survey DR10"


def test_sherlock_crossmatch_maps_observed_core_science_fields():
    portfolio = _build_endpoint_payload(
        {"crossmatches": [{
            "catalogue_table_name": "SDSS/2MASS/PS1", "catalogue_table_id": 1,
            "catalogue_object_id": "1237673709862061782", "catalogue_object_type": "galaxy",
            "association_type": "SN", "classification": "fallback",
            "classificationReliability": "2", "raDeg": "124.88026", "decDeg": "-6.02082",
            "separationArcsec": "1.5719427375338366", "northSeparationArcsec": "-1.15164",
            "eastSeparationArcsec": "1.06992", "photoZ": "0.123", "photoZErr": "0.004",
            "z": None, "rank": "1", "merged_rank": "9",
        }]},
        "sherlock_position",
    )
    record = next(r for r in portfolio.records if r.semantic_type == "crossmatch@sdss_2mass_ps1:lasair")
    fields = dict(record.fields)
    assert fields["identity.object_id"] == "1237673709862061782"
    assert fields["provenance.producer.name"] == "SDSS/2MASS/PS1"
    assert fields["provenance.producer.id"] == "sdss_2mass_ps1"
    assert fields["position.ra"] == 124.88026
    assert fields["position.dec"] == -6.02082
    assert fields["separation.total"] == 1.5719427375338366
    assert fields["separation.north"] == -1.15164
    assert fields["separation.east"] == 1.06992
    assert "redshift.value" not in fields
    assert "redshift.error" not in fields
    assert "redshift.native_z" not in fields
    assert fields["rank"] == 1
    assert fields["classification.assessment.catalogue.class"] == "galaxy"
    assert fields["classification.assessment.sherlock.class"] == "SN"
    assert fields["classification.assessment.sherlock.score"] == 2.0
    assert portfolio.edges == ()


def test_sherlock_crossmatch_merged_rank_does_not_populate_rank():
    portfolio = _build_endpoint_payload(
        {"crossmatches": [{"catalogue_table_name": "2MASS PSC", "catalogue_table_id": 2,
                           "catalogue_object_id": "abc", "rank": None, "merged_rank": "3"}]},
        "sherlock_position",
    )
    record = next(r for r in portfolio.records if r.semantic_type == "crossmatch@twomass:lasair")
    assert "rank" not in dict(record.fields)


def test_sherlock_crossmatch_redshift_z_wins_over_photo_z():
    portfolio = _build_endpoint_payload(
        {"crossmatches": [{
            "catalogue_table_name": "Million Quasars (MILLIQUAS) Catalog v8.0",
            "catalogue_object_id": "SDSS J122001.73+082413.4",
            "z": 2.492, "photoZ": 0.111, "photoZErr": 0.004,
        }]},
        "sherlock_position",
    )
    record = next(r for r in portfolio.records if r.semantic_type == "crossmatch@milliquas:lasair")
    fields = dict(record.fields)
    assert fields["redshift.value"] == 2.492
    assert "redshift.error" not in fields
    assert "redshift.native_z" not in fields


def test_sherlock_crossmatch_maps_projected_separation():
    portfolio = _build_endpoint_payload(
        {"crossmatches": [{
            "catalogue_table_name": "Million Quasars (MILLIQUAS) Catalog v8.0",
            "catalogue_object_id": "SDSS J122001.73+082413.4",
            "separationArcsec": 0.030735851265057398,
            "physical_separation_kpc": 0.24822273481660356,
        }]},
        "sherlock_position",
    )
    record = next(r for r in portfolio.records if r.semantic_type == "crossmatch@milliquas:lasair")
    fields = dict(record.fields)
    assert fields["separation.total"] == 0.030735851265057398
    assert fields["separation.projected"] == 0.24822273481660356


def test_sherlock_crossmatch_maps_distance_estimates_and_skips_null_numbers():
    source = "Million Quasars (MILLIQUAS) Catalog v8.0"
    portfolio = _build_endpoint_payload(
        {"crossmatches": [{
            "catalogue_table_name": "SDSS/MILLIQUAS/GAIA/DESI/PS1",
            "catalogue_object_id": "1237661972796145844",
            "best_distance": 20313.445, "best_distance_flag": "sz",
            "best_distance_source": source,
            "z_distance": 20313.445, "z_distance_cat": source,
            "z_distance_modulus": 46.539, "z_distance_scale": 8.076,
            "pz_distance": None, "pz_distance_cat": source,
            "pz_distance_modulus": None, "pz_distance_scale": None,
            "direct_distance": None, "direct_distance_cat": source,
            "direct_distance_modulus": None, "direct_distance_scale": None,
        }]},
        "sherlock_position",
    )
    record = next(
        r for r in portfolio.records
        if r.semantic_type == "crossmatch@sdss_milliquas_gaia_desi_ps1:lasair"
    )
    fields = dict(record.fields)
    assert fields["distance.estimate.best.value"] == 20313.445
    assert fields["distance.estimate.best.flag"] == "sz"
    assert fields["distance.estimate.best.source"] == source
    assert fields["distance.estimate.redshift.value"] == 20313.445
    assert fields["distance.estimate.redshift.source"] == source
    assert fields["distance.estimate.redshift.modulus"] == 46.539
    assert fields["distance.estimate.redshift.scale"] == 8.076
    for estimate in ("photometric_redshift", "direct"):
        for quantity in ("value", "modulus", "scale"):
            assert f"distance.estimate.{estimate}.{quantity}" not in fields


def test_sherlock_objects_crossmatch_maps_distance_and_projected_separation():
    portfolio = _build_endpoint_payload(
        {"crossmatches": [{
            "catalogue_table_name": "Gaia DR3",
            "catalogue_object_id": 3902146494731655680,
            "z_distance": "123.4", "z_distance_modulus": "35.1",
            "z_distance_scale": "2.3", "physical_separation_kpc": "0.5",
        }]},
        "sherlock_objects",
    )
    record = next(r for r in portfolio.records if r.semantic_type == "crossmatch@gaia:lasair")
    fields = dict(record.fields)
    assert fields["distance.estimate.redshift.value"] == 123.4
    assert fields["distance.estimate.redshift.modulus"] == 35.1
    assert fields["distance.estimate.redshift.scale"] == 2.3
    assert fields["separation.projected"] == 0.5


def test_sherlock_objects_crossmatch_maps_core_science_fields():
    portfolio = _build_endpoint_payload(
        {"crossmatches": [{"catalogue_table_name": "SDSS DR12 PhotoObjAll Table",
                            "catalogue_table_id": 4, "catalogue_object_id": "sdss-object",
                            "raDeg": "1.2", "decDeg": "3.4", "association_type": "AGN",
                            "classificationReliability": "0.9"}]},
        "sherlock_objects",
    )
    record = next(r for r in portfolio.records if r.semantic_type == "crossmatch@sdss:lasair")
    fields = dict(record.fields)
    assert fields["position.ra"] == 1.2
    assert fields["position.dec"] == 3.4
    assert fields["classification.assessment.sherlock.class"] == "AGN"
    assert fields["classification.assessment.sherlock.score"] == 0.9


def test_sherlock_crossmatch_does_not_map_photometry_or_native_audit_fields():
    portfolio = _build_endpoint_payload(
        {"crossmatches": [{"catalogue_table_name": "2MASS PSC", "catalogue_object_id": "abc",
                           "gMag": "17.2", "majorAxisArcsec": "0.4"}]},
        "sherlock_position",
    )
    record = next(r for r in portfolio.records if r.semantic_type == "crossmatch@twomass:lasair")
    assert not any(name.startswith("photometry.") for name in record.fields)
    assert not any(name.startswith("native.lasair_sherlock.") for name in record.fields)


def test_sherlock_crossmatch_unknown_producer_fallback():
    portfolio = _build_endpoint_payload(
        {
            "crossmatches": [
                {
                    "catalogue_table_name": "Some Unmapped Catalogue",
                    "catalogue_table_id": 99,
                    "catalogue_object_id": "unknown-source",
                }
            ]
        },
        "sherlock_position",
    )

    assert [record.semantic_type for record in portfolio.records] == [
        "crossmatch@unknown:lasair"
    ]
    fields = dict(portfolio.records[0].fields)
    assert fields["provenance.producer.id"] == "unknown"
    assert fields["provenance.producer.name"] == "Some Unmapped Catalogue"
    assert 99 not in fields.values()


def test_object_sherlock_crossmatch_uses_unknown_producer_fallback():
    portfolio = _build_endpoint_payload(
        {
            "objectId": "ZTF25realistic",
            "sherlock": {"catalogue_object_id": "WISEA J081336.12+221200.3"},
        },
        "object",
    )
    semantic_types = {record.semantic_type for record in portfolio.records}

    assert "crossmatch@unknown:lasair" in semantic_types
    assert "crossmatch@sherlock:lasair" not in semantic_types
    assert "crossmatch@{producer}:lasair" not in semantic_types


def test_rich_sherlock_fixture_keeps_final_and_row_assessments_distinct():
    from pathlib import Path
    payload = json.loads((Path(__file__).parent / "fixtures/lasair/ztf/sherlock_position.json").read_text())
    portfolio = _build_endpoint_payload(payload, "sherlock_position")
    final = [r for r in portfolio.records if r.semantic_type == "classification@sherlock:lasair"]
    assert len(final) == 1
    assert dict(final[0].fields)["best.class"] == "SN"
    rows = {dict(r.fields)["classification.assessment.catalogue.class"]: dict(r.fields)
            for r in portfolio.records if r.semantic_type.startswith("crossmatch@")}
    assert rows["star"]["classification.assessment.sherlock.class"] == "VS"
    assert rows["galaxy"]["classification.assessment.sherlock.class"] == "SN"
    assert rows["star"]["classification.assessment.sherlock.method"] == "2mass star angular"
    assert rows["galaxy"]["classification.assessment.sherlock.method"] == "sdss phot galaxy angular"
    assert portfolio.edges == ()
