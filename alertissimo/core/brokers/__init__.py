# alertissimo/core/brokers/__init__.py
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import Broker


_BROKER_CLASSES = {
    "alerce": (".alerce", "ALeRCEBroker"),
    "lasair": (".lasair", "LasairBroker"),
    "fink": (".fink", "FinkBroker"),
    "antares": (".antares", "AntaresBroker"),
}
_LAZY_EXPORTS = [*(_BROKER_CLASSES.values()), (".base", "Broker")]


def __getattr__(name: str):
    """Import optional broker SDK integrations only when they are requested."""
    from importlib import import_module

    for module_name, class_name in _LAZY_EXPORTS:
        if name == class_name:
            value = getattr(import_module(module_name, __name__), class_name)
            globals()[name] = value
            return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

def get_broker(name: str) -> "Broker":
    name = name.lower()
    try:
        module_name, class_name = _BROKER_CLASSES[name]
    except KeyError:
        raise ValueError(f"Unknown broker: {name}")
    from importlib import import_module

    broker_class = getattr(import_module(module_name, __name__), class_name)
    return broker_class()
