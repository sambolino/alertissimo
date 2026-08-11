from tools.audit_payload_mapping_coverage import audit_payload


def object_payload():
    return {
        "objectId": "ZTF25audit",
        "objectData": {"ncand": 1, "jdmin": 2460000.5, "jdmax": 2460001.5},
        "candidates": [{"candid": 1, "jd": 2460000.5, "magpsf": 18.1}],
    }


def extract_unmapped_branches(report: str) -> set[str]:
    section = report.split("Unmapped top-level branches:\n", 1)[1].split("\n\n", 1)[0]
    return {line.strip() for line in section.splitlines() if line.strip() != "(none)"}


def test_list_payload_definition_represents_its_top_level_branch():
    payload = object_payload()
    payload["unexpectedBranch"] = {"x": 1}
    report = audit_payload(
        payload, broker="lasair", origin="ztf", endpoint="object", payload_file="object.json"
    )

    unmapped = extract_unmapped_branches(report)
    assert "unexpectedBranch" in unmapped
    assert "candidates" not in unmapped


def test_sherlock_payload_definitions_represent_sherlock_branches():
    payload = {"classifications": {}, "crossmatches": []}
    report = audit_payload(
        payload,
        broker="lasair",
        origin="ztf",
        endpoint="sherlock_position",
        payload_file="sherlock_position.json",
    )

    assert extract_unmapped_branches(report) == set()
    assert "Portfolio records: 0" in report
    assert "No semantic records were built for this endpoint/payload shape." in report
