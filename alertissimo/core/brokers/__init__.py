"""Broker adapters and registry helpers.

Adapters are imported lazily so registry-only tools do not require every
optional broker client to be installed.
"""

from importlib import import_module
from typing import Any


_ADAPTERS = {
    "alerce": ("alerce", "ALeRCEBroker"),
    "lasair": ("lasair", "LasairBroker"),
    "fink": ("fink", "FinkBroker"),
    "antares": ("antares", "AntaresBroker"),
}
_EXPORTED_ADAPTERS = {class_name: module for module, class_name in _ADAPTERS.values()}
_EXPORTED_ADAPTERS["Broker"] = "base"


def __getattr__(name: str):
    """Preserve package-level adapter imports without eagerly loading clients."""
    module_name = _EXPORTED_ADAPTERS.get(name)
    if module_name is None:
        raise AttributeError(name)
    return getattr(import_module(f"{__name__}.{module_name}"), name)


def get_broker(name: str) -> Any:
    """Construct an adapter by its case-insensitive broker name."""
    adapter = _ADAPTERS.get(name.lower())
    if adapter is None:
        raise ValueError(f"Unknown broker: {name}")
    module_name, class_name = adapter
    adapter_class = getattr(import_module(f"{__name__}.{module_name}"), class_name)
    return adapter_class()


__all__ = ["get_broker", *_EXPORTED_ADAPTERS]
