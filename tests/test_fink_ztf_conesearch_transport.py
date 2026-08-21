"""Regression for the live Fink/ZTF cone-search transport contract."""

import json
from pathlib import Path

from alertissimo.data_layer.execution import EndpointRegistry, RestTransport


REGISTRY = Path(__file__).parents[1] / "alertissimo/data_layer/providers"


def test_fink_ztf_conesearch_uses_post_json(monkeypatch):
    spec = EndpointRegistry(REGISTRY).resolve("fink", "ztf", "conesearch")

    assert spec.method == "POST"
    assert spec.request_encoding == "json"

    captured = {}

    class Headers:
        @staticmethod
        def get_content_type():
            return "application/json"

    class Response:
        status = 200
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        @staticmethod
        def read():
            return b"[]"

    def fake_urlopen(request):
        captured["request"] = request
        return Response()

    monkeypatch.setattr(
        "alertissimo.data_layer.execution.transports.urlopen", fake_urlopen
    )

    params = {
        "ra": 124.87996115142856,
        "dec": -6.0205001,
        "radius": 300.0,
    }
    RestTransport().execute(spec, params)

    request = captured["request"]
    assert request.method == "POST"
    assert request.full_url == "https://api.ztf.fink-portal.org/api/v1/conesearch"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == params
