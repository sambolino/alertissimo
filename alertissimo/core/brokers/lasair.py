# alertissimo/core/brokers/lasair.py
from .base import Broker
from alertissimo.config import LASAIR_TOKEN
from typing import Optional

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

    def get_crossmatch(self, object_id: str, data: Optional):
        return self.get_sherlock(object_id)

    def get_sherlock(self, object_id: str):
        return self.request(
            endpoint="sherlock/object/",
            params={"objectId": object_id},
            include_token=True,
            format="json"
        )
    
    def extract_multiband_crossmatches(sherlock_data: dict) -> dict:
        result = {"IR": [], "X": [], "UV": []}
        for cm in sherlock_data.get("crossmatches", []):
            cat = cm.get("catalogue", "").lower()
            if "wise" in cat or "2mass" in cat:
                result["IR"].append(cm)
            elif "xmm" in cat or "rosat" in cat or "chandra" in cat or "erosita" in cat:
                result["X"].append(cm)
            elif "galex" in cat:
                result["UV"].append(cm)
        return result

    def is_kafka_monitored(self, object_id: str) -> bool:
        # In real setup, we'd listen for updates here
        return True
    
    def is_available(self) -> bool:
        return bool(self.token)
