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

    def get_crossmatch(self, object_id, data):
        return self.extract_xray_matches(data)

    def extract_xray_matches(self, locus) -> list[dict]:
        """Extract crossmatches from ANTARES locus object for X-ray catalogs like eROSITA."""
        matches = []

        if not hasattr(locus, "catalog_objects") or not locus.catalog_objects:
            logger.info("ANTARES locus has no catalog_objects.")
            return []

        logger.info(f"ANTARES catalogs found: {list(locus.catalog_objects.keys())}")

        for catalog_name, objects in locus.catalog_objects.items():
            logger.debug(f"Catalog {catalog_name} has {len(objects)} objects")
            if catalog_name.lower() == "erosita":
                matches.extend(objects)

        logger.info(f"Found {len(matches)} eROSITA matches from ANTARES.")
        return matches

    def is_available(self) -> bool:
        return HAS_ANTARES
