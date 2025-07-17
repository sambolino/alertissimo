# alertissimo/core/brokers/alerce.py
from .base import Broker

class ALeRCEBroker(Broker):
    def __init__(self):
        super().__init__(
            name="ALeRCE",
            base_url="https://api.alerce.online/ztf/v1"
        )

    def get_object_data(self, object_id: str):
        return self.request(
            endpoint="objects/",
            params={"oid": object_id}
        )

    def get_lightcurve(self, object_id: str):
        endpoint = f"objects/{object_id}/lightcurve"
        return self.request(endpoint)

    def is_available(self) -> bool:
        # alerce REST api is publicly available without credentials
        return True 
