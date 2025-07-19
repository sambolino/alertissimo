# alertissimo/core/brokers/base.py
import requests
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union, Iterator
from astropy.coordinates import SkyCoord
from astropy.units import Quantity
from alertissimo.config import DEFAULT_TIMEOUT

logger = logging.getLogger("broker")

class Broker(ABC):
    def __init__(self, name: str, base_url: str, token: Optional[str] = None):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request(
        self,
        endpoint: str,
        params: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        include_token: bool = False,
    ) -> Optional[dict]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        query_params = params.copy() if params else {}

        if include_token and self.token:
            query_params["token"] = self.token

        try:
            response = requests.get(url, params=query_params, headers=headers, timeout=DEFAULT_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"{self.name} error at {url}: {e}")
            return None


    @abstractmethod
    def is_available(self) -> bool:
        """Return True if credentials/configs required for this broker exist."""
        return self.token is not None

    def ping(self) -> bool:
        """Generic ping method that uses broker's get_object_data with a dummy object ID."""
        # not yet used, test what's a safe dummy ID
        test_object_id = "ZTFfake"  # or a broker-safe dummy ID
        try:
            response = self.get_object_data(test_object_id)
            return response is not None
        except NotImplementedError:
            logger.warning(f"{self.name} does not implement get_object_data.")
            return False
        except Exception as e:
            logger.warning(f"{self.name} ping failed: {e}")
            return False

    @abstractmethod
    def conesearch(self, ra: float, dec: float, radius: float, **kwargs) -> Any:
        """Search for objects within a sky region."""
        pass

    @abstractmethod
    def object_query(self, object_id: str, **kwargs) -> Any:
        """Query object by ID."""
        pass

    @abstractmethod
    def objects_query(self, object_ids: Optional[List[str]], **kwargs) -> Iterator[Any]:
        """Query objects by list of ID's. and/or other arguments"""
        pass

    @abstractmethod
    def sql_query(self, query: str, **kwargs) -> Iterator[Any]:
        """Query broker with raw ElasticSearch dictionary."""
        pass

    @abstractmethod
    def kafka_stream(self, **kwargs) -> Iterator[Any]:
        """Open a live stream of alerts (if available)."""
        pass

    @abstractmethod
    def lightcurve(self, object_id: str, **kwargs) -> Any:
        """Retrieve light curve for a specific object."""
        pass

    @abstractmethod
    def classifications(self, object_id: str, **kwargs) -> Any:
        """Get classification probabilities or labels for a given object."""
        pass

    @abstractmethod
    def forced_photometry(self, ra: float, dec: float, jd: float, **kwargs) -> Any:
        """Request forced photometry at specified coordinates and time."""
        pass

    @abstractmethod
    def crossmatch(self, object_id: str, catalog: Optional[str] = None, **kwargs) -> Any:
        """Perform a crossmatch of an object against a known catalog."""
        pass

    @abstractmethod
    def view_url(self, object_id: str) -> str:
        """Return a browser-viewable URL for the object (if applicable)."""
        pass
