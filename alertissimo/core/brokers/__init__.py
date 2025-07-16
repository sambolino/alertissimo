# alertissimo/core/brokers/__init__.py
from .alerce import ALeRCEBroker
from .lasair import LasairBroker
from .fink import FinkBroker
from .antares import AntaresBroker
from .base import Broker
import os

def get_broker(name: str) -> Broker:
    name = name.lower()
    
    if name == "alerce":
        return ALeRCEBroker()
    
    elif name == "lasair":
        return LasairBroker()

    elif name == "fink":
        return FinkBroker()
    
    elif name == "antares":
        return AntaresBroker()
    
    else:
        raise ValueError(f"Unknown broker: {name}")
