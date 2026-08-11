from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "tools" / "capture_alerce_ztf_payloads.py"
SPEC = spec_from_file_location("capture_alerce_ztf_payloads", SCRIPT)
assert SPEC and SPEC.loader
capture = module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


@pytest.mark.parametrize(
    ("value", "error", "status"),
    [
        ([{"oid": "ZTF1"}], None, "ok"),
        ([], None, "empty"),
        (None, RuntimeError("no"), "failed"),
    ],
)
def test_result_entry_status(value, error, status):
    assert capture._result_entry(value, error=error)["status"] == status


def test_json_value_preserves_rows_and_nulls():
    assert capture._json_value([{"fid": 1, "mag": None}]) == [{"fid": 1, "mag": None}]


def test_invocation_uses_only_supported_multisurvey_arguments():
    def with_survey(*, oid, survey, format):
        pass

    def without_survey(*, oid, format):
        pass

    assert capture._invocation(with_survey, "query_object", "ZTF1") == {
        "oid": "ZTF1",
        "survey": "ztf",
        "format": "json",
    }
    assert capture._invocation(without_survey, "query_object", "ZTF1") == {
        "oid": "ZTF1",
        "format": "json",
    }


def test_invocation_rejects_incompatible_discovery_signature():
    def incompatible(*, page):
        pass

    with pytest.raises(TypeError, match="does not support configured arguments"):
        capture._invocation(incompatible, "query_objects")
