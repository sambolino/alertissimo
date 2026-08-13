from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

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
    def incompatible(*, oid):
        pass

    with pytest.raises(TypeError, match="does not support configured arguments"):
        capture._invocation(incompatible, "query_objects")


def test_query_objects_uses_known_oids_and_reads_real_wrapper_shape():
    def query_objects(*, oid, survey, format):
        pass

    assert capture._invocation(query_objects, "query_objects") == {
        "oid": list(capture.KNOWN_OBJECTS),
        "survey": "ztf",
        "format": "json",
    }
    value = {"items": [{"oid": "ZTF1"}], "total": None}
    entry = capture._result_entry(value, query=list(capture.KNOWN_OBJECTS))
    assert entry == {
        "status": "ok",
        "query": list(capture.KNOWN_OBJECTS),
        "shape": "dict keys=['items', 'total']",
    }
    assert len(value["items"]) == 1


def test_finite_timeout_preserves_explicit_request_timeout(monkeypatch):
    seen = []

    def original(session, method, url, **kwargs):
        seen.append(kwargs["timeout"])

    class Session:
        request = original

    requests = SimpleNamespace(sessions=SimpleNamespace(Session=Session), Session=Session)
    with capture._finite_http_timeout(20, requests):
        session = requests.Session()
        session.request("GET", "https://example.invalid")
        session.request("GET", "https://example.invalid", timeout=3)
    assert seen == [20, 3]


def test_client_type_error_is_recorded_as_execution_failure(tmp_path, monkeypatch, capsys):
    class FakeAlerce:
        def query_objects(self, *, oid, survey, format):
            raise TypeError("raised inside official client")

    for endpoint in capture.OBJECT_ENDPOINTS:
        setattr(FakeAlerce, endpoint, lambda self, *, oid, format: [])

    core = ModuleType("alerce.core")
    core.Alerce = FakeAlerce
    package = ModuleType("alerce")
    package.core = core
    class Session:
        def request(self, method, url, **kwargs):
            pass

    requests = ModuleType("requests")
    requests.sessions = SimpleNamespace(Session=Session)
    monkeypatch.setitem(sys.modules, "alerce", package)
    monkeypatch.setitem(sys.modules, "alerce.core", core)
    monkeypatch.setitem(sys.modules, "requests", requests)

    assert capture.capture(tmp_path) == 1
    manifest = __import__("json").loads((tmp_path / "capture_manifest.json").read_text())
    assert manifest["calls"]["query_objects"]["status"] == "failed"
    assert "raised inside official client" in manifest["calls"]["query_objects"]["error"]
    assert all(
        manifest["calls"][endpoint]["status"] == "empty"
        for endpoint in capture.OBJECT_ENDPOINTS
    )
    assert "query_objects: requesting" in capsys.readouterr().out
