# alertissimo/core/brokers/base.py
import requests
import logging
from typing import Optional, Dict
from abc import ABC, abstractmethod

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
        format: Optional[str] = "json"
    ) -> Optional[dict]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        query_params = params.copy() if params else {}

        if include_token and self.token:
            query_params["token"] = self.token

        if format:
            query_params["format"] = format

        try:
            response = requests.get(url, params=query_params, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"{self.name} error at {url}: {e}")
            return None

    @abstractmethod
    def get_object_data(self, object_id: str) -> Optional[dict]:
        raise NotImplementedError

    def get_lightcurve(self, object_id: str) -> Optional[dict]:
        raise NotImplementedError

    def get_crossmatch(self, object_id: str, data: Optional[str]) -> Optional[dict]:
        raise NotImplementedError

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

