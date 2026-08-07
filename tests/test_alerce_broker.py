from unittest.mock import Mock

from alertissimo.core.brokers.alerce import ALeRCEBroker


def _broker_with_mock_client():
    broker = ALeRCEBroker()
    broker.client = Mock()
    return broker


def test_findobject_uses_alerce_client():
    broker = _broker_with_mock_client()
    broker.client.query_object.return_value = {"oid": "ZTF20aaelulu"}

    result = broker.findobject("ZTF20aaelulu")

    broker.client.query_object.assert_called_once_with(
        "ZTF20aaelulu", survey="ztf", format="json"
    )
    assert result == {"summary": {"oid": "ZTF20aaelulu"}}


def test_lightcurve_and_forced_photometry_use_alerce_client():
    broker = _broker_with_mock_client()

    broker.lightcurve("ZTF20aaelulu")
    broker.forced_photometry("ZTF20aaelulu")

    broker.client.query_lightcurve.assert_called_once_with(
        "ZTF20aaelulu", survey="ztf", format="json"
    )
    broker.client.query_forced_photometry.assert_called_once_with(
        "ZTF20aaelulu", survey="ztf", format="json"
    )
