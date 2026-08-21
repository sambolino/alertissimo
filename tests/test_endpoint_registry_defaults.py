from pathlib import Path

import pytest
import yaml

from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor


REGISTRY = Path(__file__).parents[1] / "alertissimo/data_layer/providers"
DYNAMIC_TIME_SENTINELS = {"now", "today"}


def test_registry_does_not_encode_dynamic_time_sentinels_as_client_defaults():
    offenders = []

    for path in sorted(REGISTRY.glob("*/*/endpoints.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        broker = document.get("broker")
        origin = document.get("origin")

        for endpoint, endpoint_spec in (document.get("endpoints") or {}).items():
            for name, contract in (endpoint_spec.get("params") or {}).items():
                if not isinstance(contract, dict) or "default" not in contract:
                    continue
                default = contract["default"]
                if (
                    isinstance(default, str)
                    and default.strip().lower() in DYNAMIC_TIME_SENTINELS
                ):
                    offenders.append(
                        f"{broker}/{origin}/{endpoint}.{name}={default!r}"
                    )

    assert offenders == []


@pytest.mark.parametrize(
    ("endpoint", "stop_param", "supplied"),
    [
        (
            "conesearch",
            "stopdate",
            {"ra": 124.87996115142856, "dec": -6.0205001, "radius": 300.0},
        ),
        ("latests", "stopdate", {"class": "SN candidate"}),
        ("anomaly", "stop_date", {}),
    ],
)
def test_fink_ztf_provider_owned_current_time_defaults_remain_omitted(
    endpoint, stop_param, supplied
):
    spec = EndpointRegistry(REGISTRY).resolve("fink", "ztf", endpoint)

    assert "default" not in spec.params[stop_param]
    validated = RegistryEndpointExecutor._validated_params(spec, supplied)
    assert stop_param not in validated
