# alertissimo/core/brokers/lasair.py
from .base import Broker
from alertissimo.config import LASAIR_TOKEN

class LasairBroker(Broker):
    def __init__(self):
        super().__init__(
            name="Lasair",
            base_url="https://lasair-ztf.lsst.ac.uk/api",
            token=LASAIR_TOKEN
        )

    def get_object_data(self, object_id: str):
        return self.request(
            endpoint="object/",
            params={"objectId": object_id},
            include_token=True,
            format="json"
        )
