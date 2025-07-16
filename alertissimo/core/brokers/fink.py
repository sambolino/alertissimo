# alertissimo/core/brokers/fink.py
from .base import Broker

class FinkBroker(Broker):
    def __init__(self):
        super().__init__(name="Fink", base_url="https://fink-portal.org/api")

    def get_object_data(self, object_id: str):
        # Stub: no real Fink public API yet
        return {"objectId": object_id, "stub": True}

