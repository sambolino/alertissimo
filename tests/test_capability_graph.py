import pytest

from alertissimo.core.brokers.registry.capabilities import (
    CapabilityGraphError,
    endpoint_capabilities,
)


def test_endpoint_capability_uses_normalized_top_level_path_and_method():
    capabilities = endpoint_capabilities({
        "broker": "example",
        "origin": "ztf",
        "endpoints": {
            "objects": {
                "path": "/api/v1/objects",
                "method": "POST",
                "transport": {"path": "/legacy", "method": "GET"},
            }
        },
    })

    assert capabilities[0].path == "/api/v1/objects"
    assert capabilities[0].method == "POST"


@pytest.mark.parametrize("missing", ["path", "method"])
def test_endpoint_capability_does_not_fall_back_to_transport(missing):
    specification = {
        "path": "/api/v1/objects",
        "method": "POST",
        "transport": {"path": "/legacy", "method": "GET"},
    }
    specification.pop(missing)

    with pytest.raises(CapabilityGraphError, match=missing):
        endpoint_capabilities({
            "broker": "example",
            "origin": "ztf",
            "endpoints": {"objects": specification},
        })


@pytest.mark.parametrize(("field", "value"), [("path", None), ("method", 1)])
def test_endpoint_capability_requires_string_path_and_method(field, value):
    specification = {"path": "/api/v1/objects", "method": "POST"}
    specification[field] = value

    with pytest.raises(CapabilityGraphError, match=field):
        endpoint_capabilities({
            "broker": "example",
            "origin": "ztf",
            "endpoints": {"objects": specification},
        })
