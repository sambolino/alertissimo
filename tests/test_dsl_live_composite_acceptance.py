"""Offline replay of live acceptance after the composite-cone recipe migration."""

from types import SimpleNamespace

import pytest

from scripts import live_dsl_complex, live_dsl_continuation
from scripts.smoke.executors import FixtureEndpointExecutor, fixture_key


OBJECT_ID = "ZTF20acpwljl"
CAPTURE = "../../../tests/fixtures/lasair/ztf/capture_20260813T110413Z/"


def fixture_executor(fail_call):
    return FixtureEndpointExecutor({
        fixture_key("lasair", "ztf", "cone", ra=124.87996115142856, dec=-6.0205001, radius=5.0):
            CAPTURE + "cone_all.json",
        fixture_key("lasair", "ztf", "query", selected=(
            "objects.objectId,objects.ramean,objects.decmean,objects.ncand,objects.jdmin,objects.jdmax"
        ), tables="objects", limit=100, offset=0, conditions=f'objects.objectId IN ("{OBJECT_ID}")'):
            CAPTURE + "query_core.json",
        fixture_key("fink", "ztf", "objects", objectId=OBJECT_ID):
            "fink_objects_ztf20acpwljl_quality.json",
        fixture_key("lasair", "ztf", "lightcurves", objectIds=OBJECT_ID):
            "lasair_lightcurves_ztf20acpwljl.json",
    }, fail_call=fail_call)


@pytest.mark.parametrize("fail_call", [None, 2], ids=["summary-success", "summary-failure"])
def test_cross_provider_live_script_accepts_composite_discovery(monkeypatch, fail_call):
    executor = fixture_executor(fail_call)
    monkeypatch.setattr(live_dsl_complex, "load_dotenv", lambda **kwargs: None)
    monkeypatch.setattr(live_dsl_complex, "RegistryEndpointExecutor", lambda **kwargs: executor)

    assert live_dsl_complex.main() == 0
    assert [call[2] for call in executor.calls] == ["cone", "query", "objects", "lightcurves"]


@pytest.mark.parametrize("fail_call", [None, 2], ids=["summary-success", "summary-failure"])
def test_live_continuation_replays_composite_discovery(monkeypatch, fail_call):
    executor = fixture_executor(fail_call)
    monkeypatch.setattr(live_dsl_continuation, "load_dotenv", lambda **kwargs: None)
    monkeypatch.setattr(live_dsl_continuation, "RegistryEndpointExecutor", lambda **kwargs: executor)
    monkeypatch.setattr(live_dsl_continuation, "_parse_args", lambda: SimpleNamespace(
        ra=124.87996115142856, dec=-6.0205001, radius_arcsec=5.0, threshold=0.8,
    ))

    # This single-object fixture keeps every candidate. The intended outcome is
    # INCONCLUSIVE after verifying replay, rather than a call-count failure.
    assert live_dsl_continuation.main() == 3
    assert [call[2] for call in executor.calls] == ["cone", "query", "objects", "lightcurves"]
    assert executor.calls[-1][3] == {"objectIds": OBJECT_ID}


def test_continuation_accepts_survivors_split_across_collection_batches():
    ids = tuple(f"target-{index}" for index in range(51))
    calls = tuple(live_dsl_continuation.RecordedCall(
        "lasair", "ztf", "lightcurves", {"objectIds": ",".join(batch)},
    ) for batch in (ids[:50], ids[50:]))
    live_dsl_continuation._assert_survivor_calls(calls, ids)

    with pytest.raises(RuntimeError, match="binding differs from Filter survivors"):
        live_dsl_continuation._assert_survivor_calls(calls + calls[-1:], ids)
    with pytest.raises(RuntimeError, match="binding differs from Filter survivors"):
        live_dsl_continuation._assert_survivor_calls(calls[:1], ids)


def test_first_pass_rejects_unplanned_executor_calls():
    from alertissimo.api import execute_dsl

    executor = fixture_executor(None)
    first = execute_dsl("""objects from ztf via lasair
inside (124.87996115142856, -6.0205001, 5arcsec)
with lightcurve via fink
""", executor=executor)
    calls = tuple(live_dsl_continuation.RecordedCall(*call) for call in executor.calls)
    live_dsl_continuation._assert_first_pass_calls(first, calls)
    with pytest.raises(RuntimeError, match="differ from staged physical bindings"):
        live_dsl_continuation._assert_first_pass_calls(first, calls + calls[:1])
