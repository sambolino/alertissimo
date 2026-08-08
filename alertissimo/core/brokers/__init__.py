# alertissimo/core/brokers/__init__.py
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .alerce import ALeRCEBroker
    from .antares import AntaresBroker
    from .base import Broker
    from .fink import FinkBroker
    from .lasair import LasairBroker


def __getattr__(name: str) -> Any:
    """Load optional broker clients only when their class is requested."""
    modules = {
        "ALeRCEBroker": (".alerce", "ALeRCEBroker"),
        "AntaresBroker": (".antares", "AntaresBroker"),
        "FinkBroker": (".fink", "FinkBroker"),
        "LasairBroker": (".lasair", "LasairBroker"),
        "Broker": (".base", "Broker"),
    }
    if name not in modules:
        raise AttributeError(name)
    from importlib import import_module

    module_name, class_name = modules[name]
    return getattr(import_module(module_name, __name__), class_name)


def get_broker(name: str) -> Any:
    name = name.lower()

    if name == "alerce":
        from .alerce import ALeRCEBroker
        return ALeRCEBroker()
    elif name == "lasair":
        from .lasair import LasairBroker
        return LasairBroker()
    elif name == "fink":
        from .fink import FinkBroker
        return FinkBroker()
    elif name == "antares":
        from .antares import AntaresBroker
        return AntaresBroker()

    else:
        raise ValueError(f"Unknown broker: {name}")
