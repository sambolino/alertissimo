# alertissimo/core/brokers/antares.py
from .base import Broker
from astropy.coordinates import SkyCoord, Angle
from typing import Optional, List, Iterator, Any
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

    def normalize_object(
        self,
        raw_data: list,
        include_summary: bool = False,
        include_raw: bool = False,
    ) -> dict:
        if not raw_data:
            return {}

        result = {}

        # Summary - aggregate information
        if include_summary:
            result["summary"] = raw_data

        # Raw data
        if include_raw:
            result["raw"] = raw_data

        return result


    def is_available(self) -> bool:
        return HAS_ANTARES

    def conesearch(self, ra: float, dec: float, radius: float, **kwargs) -> Iterator[Any]:
        skycoord = SkyCoord(ra=ra, dec=dec, unit="deg")
        angle = Angle(radius, unit="deg")
        return antares_client.search.cone_search(center=skycoord, radius=angle)

    def object_query(self, object_id: str, **kwargs) -> Any:
        raw_data = antares_client.search.get_by_ztf_object_id(object_id).properties
        return self.normalize_object(raw_data, include_summary = True)

    def objects_query(self, object_ids: List[str], **kwargs) -> Iterator[Any]:
        objects = []
        for oid in object_ids:
            objects.append(antares_client.search.get_by_ztf_object_id(oid))

    def sql_query(self, query: str, **kwargs) -> Iterator[Any]:
        # TODO convert sql to elastic dict and call antares_client.search.search
        raise NotImplementedError


    def kafka_stream(self, **kwargs) -> Iterator[Any]:
        # TODO call antares_client.StreamingClient
        raise NotImplementedError

    def lightcurve(self, object_id: str, **kwargs) -> Any:
        # TODO
        raise NotImplementedError

    def classifications(self, object_id: str, **kwargs) -> Any:
        # TODO
        raise NotImplementedError

    def forced_photometry(self, ra: float, dec: float, jd: float, **kwargs) -> Any:
        # TODO?
        raise NotImplementedError

    def crossmatch(self, object_id, catalog: Optional[str] = None):
        return self.extract_xray_matches(self.object_query(object_id))

    def view_url(self, object_id: str) -> str:
        # TODO?
        raise NotImplementedError

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

