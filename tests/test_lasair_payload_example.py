import json
import subprocess
import sys

from examples.build_lasair_portfolio_from_payload import build_portfolio_from_payload
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
    assert "classification@lasair" in semantic_types
    assert "crossmatch@unknown:lasair" in semantic_types
    assert "crossmatch@{producer}:lasair" not in semantic_types
    assert "crossmatch@sherlock:lasair" not in semantic_types
    assert portfolio.edges == ()
    assert sum(record.semantic_type == "detection@ztf:lasair" for record in portfolio.records) == 3
    assert portfolio.executions[0].params == {"objectId": "ZTF25realistic"}


def test_sherlock_position_real_payload_shape_normalizes_catalogues_and_rank():
    payload = {
        "classifications": {
            "ZTF20acpwljl": ["SN", "The transient is possibly associated"],
        },
        "crossmatches": [
            {"catalogue_object_id": "1237673709862061782 ",
             "catalogue_table_name": "SDSS/2MASS/PS1", "rank": 1, "z": None,
             "photoZ": 0.129075, "photoZErr": 0.03112, "raDeg": 120.1,
             "decDeg": -6.0, "separationArcsec": 0.4, "g": 18.2},
            {"catalogue_object_id": "08193126-0601149 ",
             "catalogue_table_name": "2MASS PSC", "merged_rank": 2, "z": None,
             "raDeg": 120.2, "decDeg": -6.1, "separationArcsec": 0.8, "J": 16.1},
        ],
    }
    provenance = InternalExecutionProvenance(
        internal_execution_id=InternalExecutionId("execution:sherlock"), broker="lasair",
        origin="ztf", endpoint="sherlock_position",
    )
    portfolio = build_portfolio_from_execution(
        ExecutionResult(payload=payload, execution_provenance=provenance)
    )
    records = {record.semantic_type: record for record in portfolio.records}
    assert {"crossmatch@sdss_2mass_ps1:lasair", "crossmatch@twomass:lasair",
            "classification@sherlock:lasair"} <= records.keys()
    assert not any("{producer}" in record.semantic_type for record in portfolio.records)
    assert "crossmatch@unknown:lasair" not in records
    assert "crossmatch@sherlock:lasair" not in records
    first = records["crossmatch@sdss_2mass_ps1:lasair"].fields
    second = records["crossmatch@twomass:lasair"].fields
    assert "redshift.native_z" not in first and "redshift.native_z" not in second
    assert first["rank"] == 1 and isinstance(first["rank"], int)
    assert second["rank"] == 2 and isinstance(second["rank"], int)
    classification = records["classification@sherlock:lasair"].fields
    assert classification["best.class"] == "SN"
    assert classification["identity.object_id"] == "ZTF20acpwljl"
    assert portfolio.edges == ()


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
    assert "No semantic records were built for this endpoint/payload shape." in result.stderr
