"""ANTARES cone-search binding stays declarative and provider-neutral."""

import pytest

from alertissimo.data_layer.execution.registry import EndpointRegistry
from alertissimo.orchestration.binding import binder as binder_module
from alertissimo.orchestration.ir import ConeSearchStep
from alertissimo.orchestration.runtime import EndpointPlan


@pytest.mark.parametrize("origin", ["ztf", "lsst"])
def test_antares_cone_composes_canonical_roles_into_native_parameters(
    monkeypatch, origin
):
    loaded: list[str] = []

    def fake_loader(path: str):
        loaded.append(path)
        if path.endswith(":skycoord_icrs_degrees"):
            return lambda **values: (
                "SkyCoord",
                float(values["ra"]),
                float(values["dec"]),
            )
        if path.endswith(":angle_arcsec"):
            return lambda **values: ("Angle", float(values["radius"]))
        raise AssertionError(f"unexpected binding adapter {path!r}")

    monkeypatch.setattr(binder_module, "_load_binding_adapter", fake_loader)

    call = binder_module.bind_endpoint(
        ConeSearchStep(
            semantic_type="summary",
            ra=124.87996115142856,
            dec=-6.0205001,
            radius=1.0,
        ),
        EndpointPlan(broker="antares", origin=origin, endpoint="cone_search"),
        EndpointRegistry(),
    )

    assert call.params == {
        "center": ("SkyCoord", 124.87996115142856, -6.0205001),
        "radius": ("Angle", 1.0),
    }
    assert call.endpoint_spec.params["center"]["binding"]["roles"] == ["ra", "dec"]
    assert call.endpoint_spec.params["radius"]["bind"] == "radius"
    assert loaded == [
        "alertissimo.data_layer.providers.antares_binding:skycoord_icrs_degrees",
        "alertissimo.data_layer.providers.antares_binding:angle_arcsec",
    ]


def test_antares_binding_adapter_module_has_no_eager_astropy_import():
    # Focused orchestration CI intentionally does not install provider-heavy optional
    # dependencies. Merely loading the provider adapter module must therefore remain
    # safe; Astropy is imported only when a live ANTARES cone call is actually bound.
    from alertissimo.data_layer.providers import antares_binding

    assert callable(antares_binding.skycoord_icrs_degrees)
    assert callable(antares_binding.angle_arcsec)
