from tools.audit_payload_mapping_coverage import audit_payload


def _unmapped_branches(report: str) -> set[str]:
    section = report.split("Unmapped top-level branches:\n", 1)[1]
    return {
        line[2:]
        for line in section.splitlines()
        if line.startswith("- ") and line != "- none"
    }


def _object_payload():
    return {
        "objectId": "ZTF25test",
        "objectData": {"ncand": 1},
        "candidates": [{"candid": 1, "jd": 2460000.5}],
    }


def test_object_payload_contract_builds_detections_without_edges():
    payload = _object_payload()
    payload["unexpectedBranch"] = {"x": 1}

    report = audit_payload(
        payload,
        broker="lasair",
        origin="ztf",
        endpoint="object",
        payload_file="object.json",
    )

    unmapped_branches = _unmapped_branches(report)
    assert "unexpectedBranch" in unmapped_branches
    assert "candidates" not in unmapped_branches


def test_sherlock_payload_branches_remain_unmapped():
    report = audit_payload(
        {"classifications": [], "crossmatches": []},
        broker="lasair",
        origin="ztf",
        endpoint="sherlock_position",
        payload_file="sherlock.json",
    )

    assert _unmapped_branches(report) == {"classifications", "crossmatches"}
