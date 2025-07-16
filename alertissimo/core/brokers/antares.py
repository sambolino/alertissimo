# alertissimo/core/brokers/antares.py
from .base import Broker
import logging

try:
    import antares_client
    HAS_ANTARES = True
except ImportError:
    HAS_ANTARES = False

logger = logging.getLogger("broker")

class AntaresBroker(Broker):
    def __init__(self):
        super().__init__(name="ANTARES", base_url="https://antares.noirlab.edu")

    def get_object_data(self, object_id: str):
        if not HAS_ANTARES:
            logger.warning("antares-client not installed.")
            return None
        try:
            return antares_client.search.get_by_ztf_object_id(object_id)
        except Exception as e:
            logger.warning(f"ANTARES error for {object_id}: {e}")
            return None

