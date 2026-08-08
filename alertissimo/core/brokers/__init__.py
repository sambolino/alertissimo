# alertissimo/core/brokers/__init__.py
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import Broker


def get_broker(name: str) -> "Broker":
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
