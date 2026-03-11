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

#    @abstractmethod
    def normalize_object(self, raw_obj: dict, **kwargs) -> dict:
        """
        Returns a standardized object dict:
        {
            "object_id": str,
            "summary": dict[str, Any],
            "lightcurve": Optional[dict or list],
            "cutouts": Optional[dict or list],
            ...
        }
        """
        pass

    def findobject(self, object_id: str, **kwargs) -> Any:
        """Query object by ID."""
        raise NotImplementedError

    def findobjects(self, object_ids: Optional[List[str]], **kwargs) -> Iterator[Any]:
        """Query objects by list of ID's. and/or other arguments"""
        raise NotImplementedError

    def conesearch(self, ra: float, dec: float, radius: Optional[float], **kwargs) -> Any:
        """Search for objects within a sky region."""
        raise NotImplementedError

    def sqlquery(self, query: str, **kwargs) -> Iterator[Any]:
        """Query broker with raw ElasticSearch dictionary."""
        raise NotImplementedError

    def kafka(self, **kwargs) -> Iterator[Any]:
        """Open a live stream of alerts (if available)."""
        raise NotImplementedError

    def lightcurve(self, object_id: str, **kwargs) -> Any:
        """Retrieve light curve for a specific object."""
        raise NotImplementedError

    def classify(self, object_id: str, **kwargs) -> Any:
        """Get classification probabilities or labels for a given object."""
        raise NotImplementedError

    def cutout(self, object_id: str, **kwargs) -> Any:
        """Get cutout image of a given object."""
        raise NotImplementedError

    ''' this is subcall of lightcurve
    @abstractmethod
    def forced_photometry(self, ra: float, dec: float, jd: float, **kwargs) -> Any:
        """Request forced photometry at specified coordinates and time."""
        pass
    '''

    def crossmatch(self, object_id: str, catalog: Optional[str] = None, **kwargs) -> Any:
        """Perform a crossmatch of an object against a known catalog."""
        raise NotImplementedError

    '''
    @abstractmethod
    def view_url(self, object_id: str) -> str:
        """Return a browser-viewable URL for the object (if applicable)."""
        pass
    '''
