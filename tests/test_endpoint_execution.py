from email.message import Message

from alertissimo.core.brokers.execution.transports import (
    EndpointSpec,
    RestTransport,
)


def test_rest_transport_encodes_get_params_in_query(monkeypatch):
    spec = EndpointSpec(
        broker="fink",
        origin="ztf",
        endpoint="objects",
        transport_kind="rest",
        method="GET",
        url="https://api.ztf.fink-portal.org/api/v1/objects",
        params={},
    )
    response_headers = Message()
    response_headers["Content-Type"] = "application/json"

    class FakeResponse:
        status = 200
        headers = response_headers

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'[{"i:objectId": "ZTF1"}]'

    def fake_urlopen(request):
        assert request.method == "GET"
        assert request.data is None
        assert "objectId=ZTF1" in request.full_url
        assert "fields=objectId%2Cra%2Cdec" in request.full_url
        return FakeResponse()

    monkeypatch.setattr(
        "alertissimo.core.brokers.execution.transports.urlopen", fake_urlopen
    )

    result = RestTransport().execute(
        spec,
        {"objectId": "ZTF1", "fields": "objectId,ra,dec"},
    )

    assert result.method == "GET"
    assert "objectId=ZTF1" in result.url
    assert result.payload == [{"i:objectId": "ZTF1"}]
    assert result.raw_size_bytes == len(b'[{"i:objectId": "ZTF1"}]')
