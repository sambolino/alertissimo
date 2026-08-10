from tools.audit_payload_mapping_coverage import audit_payload


def object_payload():
    return {
        "objectId": "ZTF1",
        "objectData": {"ncand": 1, "jdmin": 2460000.5, "jdmax": 2460001.5, "ramean": 1.0, "decmean": 2.0},
        "candidates": [{"candid": 11, "jd": 2460000.5, "ra": 1.0, "dec": 2.0, "fid": 1, "magpsf": 18.0}],
        "sherlock": {"classification": "SN"},
        "TNS": {"name": "AT1"},
    }


def test_object_payload_contract_builds_detections_without_edges():
    report = audit_payload(object_payload(), broker="lasair", origin="ztf", endpoint="object", payload_file="object.json")
    assert "- records: " in report and "- records: 0" not in report
    assert "detection@ztf:lasair" in report
    assert "- edges: 0" in report
    assert "crossmatch@{producer}:lasair" not in report.split("- semantic record types: ", 1)[1].splitlines()[0]
    assert "crossmatch@sherlock:lasair" not in report


def test_sherlock_payload_contract_is_reported_without_crashing():
    payload = {"classifications": {"ZTF1": ["SN", "candidate"]}, "crossmatches": [{"catalogue_table_name": "tns"}]}
    report = audit_payload(payload, broker="lasair", origin="ztf", endpoint="sherlock_position", payload_file="ZTF1.json")
    assert "- top-level keys: classifications, crossmatches" in report
    assert "Mapping payload definitions for endpoint:\n- none" in report
    assert "Unmapped top-level branches:\n- classifications\n- crossmatches" in report
    assert "- records: 0" in report
    assert "No semantic records were built for this endpoint/payload shape." in report
    assert "no payload definition matching this endpoint shape" in report
