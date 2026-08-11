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


def test_sherlock_position_classification_dictionary():
    portfolio = build_portfolio_from_payload(
        {
            "classifications": {
                "ZTF20acpwljl": ["SN", "The transient is possibly associated"]
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
    assert dict(records[0].fields) == {
        "identity.object_id": "ZTF20acpwljl",
        "best.class": "SN",
        "best.description": "The transient is possibly associated",
    }
    assert portfolio.edges == ()


def test_sherlock_objects_classification_dictionary():
    provenance = InternalExecutionProvenance(
        internal_execution_id=InternalExecutionId("execution:test:sherlock-objects"),
        broker="lasair",
        origin="ztf",
        endpoint="sherlock_objects",
    )
    portfolio = build_portfolio_from_execution(
        ExecutionResult(
            payload=[{"classifications": {"ZTF-object": ["AGN", "likely"]}}],
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
    assert dict(records[0].fields) == {
        "identity.object_id": "ZTF-object",
        "best.class": "AGN",
        "best.description": "likely",
    }
    assert portfolio.edges == ()
