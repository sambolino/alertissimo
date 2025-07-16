# alertissimo/core/brokers/base.py
import requests
import logging
from typing import Optional, Dict

logger = logging.getLogger("broker")

class Broker:
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

    def get_object_data(self, object_id: str) -> Optional[dict]:
        raise NotImplementedError

    def get_lightcurve(self, object_id: str) -> Optional[dict]:
        raise NotImplementedError

    def get_crossmatch(self, object_id: str, data: Optional[str]) -> Optional[dict]:
        raise NotImplementedError
