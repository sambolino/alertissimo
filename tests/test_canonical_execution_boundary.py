"""Legacy removal preserves the supported registry and import-alias contracts."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from alertissimo.data_layer.execution import RegistryEndpointExecutor


@pytest.mark.parametrize("endpoint", ["query_object", "query_lightcurve", "query_forced_photometry"])
def test_alerce_sdk_calls_go_through_canonical_registry(monkeypatch, endpoint):
    import alertissimo.data_layer.execution.transports as transport
    original = transport.importlib.import_module
    calls = []
    class Client:
        def __getattr__(self, method):
            def call(**params):
                calls.append((method, params))
                return []
            return call
    monkeypatch.setattr(transport.importlib, "import_module", lambda name: (
        SimpleNamespace(Alerce=Client) if name == "alerce.core" else original(name)))
    RegistryEndpointExecutor().execute(broker="alerce", origin="ztf", endpoint=endpoint,
                                       params={"oid": "ZTF20aaelulu"})
    assert calls == [(endpoint, {"oid": "ZTF20aaelulu", "survey": "ztf", "format": "json"})]


def test_one_workflow_model_and_no_retired_broker_factory():
    import alertissimo.api as api
    import alertissimo.core.brokers as compatibility
    from alertissimo.orchestration.ir import WorkflowIR
    assert api.WorkflowIR is WorkflowIR
    assert not hasattr(compatibility, "get_broker")


def test_repository_skill_routes_resolve_and_remain_concise():
    import yaml
    root = Path(__file__).resolve().parents[1]
    for folder in (root / ".agents/skills").iterdir():
        text = (folder / "SKILL.md").read_text()
        _, frontmatter, body = text.split("---", 2)
        meta = yaml.safe_load(frontmatter)
        assert meta["name"] == folder.name
        assert meta["description"] and len(body.splitlines()) < 100
        assert folder.name in (root / "AGENTS.md").read_text()
