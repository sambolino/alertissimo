# alertissimo/core/brokers/lasair.py
from .base import Broker
from alertissimo.config import LASAIR_TOKEN
from typing import Optional
from typing import List, Union

class LasairBroker(Broker):
    def __init__(self):
        super().__init__(
            name="Lasair",
            base_url="https://lasair-ztf.lsst.ac.uk/api",
            token=LASAIR_TOKEN
        )


    def is_kafka_monitored(self, object_id: str) -> bool:
        # In real setup, we'd listen for updates here
        return True
    
    def is_available(self) -> bool:
        return bool(self.token)

    def cone_search(
        self,
        ra: float,
        dec: float,
        radius: float,
        request_type: str = "all",
        format: str = "json"
    ):
        """
        Perform a cone search on Lasair objects.

        Parameters:
        - ra (float): Right Ascension in decimal degrees
        - dec (float): Declination in decimal degrees
        - radius (float): Search radius in arcseconds (max 1000)
        - request_type (str): 'nearest', 'all', or 'count'
        - format (str): Output format: 'json'[default], 'csv'

        Returns:
        - List of objects within search cone or count
        """
        params = {
            "ra": ra,
            "dec": dec,
            "radius": radius,
            "requestType": request_type,
            "format": format
        }
        return self.request(endpoint="cone/", params=params, include_token=True)

    def run_query(
        self,
        selected: str,
        tables: str,
        conditions: str,
        limit: int = 1000,
        offset: int = 0,
        format: str = "json"
    ):
        """
        Execute a SQL query on the Lasair database.

        Parameters:
        - selected (str): Attributes to return (comma-separated)
        - tables (str): Tables to join (comma-separated)
        - conditions (str): WHERE clause criteria
        - limit (int): Max records to return (default: 1000)
        - offset (int): Record offset (default: 0)
        - format (str): Output format: 'json'[default], 'csv'

        Returns:
        - Query results in requested format
        """
        params = {
            "selected": selected,
            "tables": tables,
            "conditions": conditions,
            "limit": limit,
            "offset": offset,
            "format": format
        }
        return self.request(endpoint="query/", params=params, include_token=True)

    def get_object(
        self,
        objectId: str,
        lasair_added: bool = True,
        format: str = "json"
    ):
        """
        Retrieve machine-readable data for a specific object.

        Parameters:
        - objectId (str): Target object identifier
        - lasair_added (bool): Include Lasair-added data (default: True)
        - format (str): Output format: 'json'[default], 'csv'

        Returns:
        - Object data including lightcurve and metadata
        """
        params = {
            "objectId": objectId,
            "lasair_added": str(lasair_added).lower(),
            "format": format
        }
        return self.request(endpoint="object/", params=params, include_token=True)

    def get_crossmatch(self, object_id: str, data: Optional):
        return self.get_sherlock_object(object_id)

    def get_sherlock_object(
        self,
        objectId: Union[str, List[str]],
        lite: bool = True,
        format: str = "json"
    ):
        """
        Retrieve Sherlock information for named objects.

        Parameters:
        - objectId (str|list): Single object ID or list of IDs (max 10)
        - lite (bool): Return simplified information (default: True)
        - format (str): Output format: 'json'[default], 'csv'

        Returns:
        - Sherlock classifications and crossmatches
        """
        # Convert list to comma-separated string
        if isinstance(objectId, list):
            objectId = ",".join(objectIds)
            
        params = {
            "objectId": objectId,
            "lite": str(lite).lower(),
            "format": format
        }
        return self.request(endpoint="sherlock/object/", params=params, include_token=True)

    def get_sherlock_position(
        self,
        ra: float,
        dec: float,
        lite: bool = True,
        format: str = "json"
    ):
        """
        Retrieve Sherlock information for a sky position.

        Parameters:
        - ra (float): Right Ascension in decimal degrees
        - dec (float): Declination in decimal degrees
        - lite (bool): Return simplified information (default: True)
        - format (str): Output format: 'json'[default], 'csv'

        Returns:
        - Sherlock classifications for the position
        """
        params = {
            "ra": ra,
            "dec": dec,
            "lite": str(lite).lower(),
            "format": format
        }
        return self.request(endpoint="sherlock/position", params=params, include_token=True)
    
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
