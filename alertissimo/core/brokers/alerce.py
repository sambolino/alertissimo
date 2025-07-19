# alertissimo/core/brokers/alerce.py
from .base import Broker
from typing import List, Optional, Union, Iterator, Any

class ALeRCEBroker(Broker):
    def __init__(self):
        super().__init__(
            name="ALeRCE",
            base_url="https://api.alerce.online/ztf/v1"
        )

    def is_available(self) -> bool:
        # alerce REST api is publicly available without credentials
        return True 

    def conesearch(self, ra: float, dec: float, radius: float, **kwargs) -> Any:
        return self.get_objects(ra=ra, dec=dec, radius=radius, **kwargs)

    def object_query(self, object_id: str, **kwargs) -> Any:
        return self.get_object(object_id)

    def objects_query(self, object_ids: Optional[List[str]], **kwargs) -> Iterator[Any]:
        return self.get_objects(object_ids, **kwargs)

    def sql_query(self, query: str, **kwargs) -> Iterator[Any]:
        # maybe break it into pieces and run via get_objects
        raise NotImplementedError

    def kafka_stream(self, **kwargs) -> Iterator[Any]:
        raise NotImplementedError

    def lightcurve(self, object_id: str, **kwargs) -> Any:
        # TODO add args for detections and nondetections
        return self.get_lightcurve(object_id, *kwargs)

    def classifications(self, object_id: str, **kwargs) -> Any:
        # TODO via get_objects
        raise NotImplementedError

    def forced_photometry(self, ra: float, dec: float, jd: float, **kwargs) -> Any:
        # TODO via get_objects?
        raise NotImplementedError

    def crossmatch(self, object_id: str, catalog: Optional[str] = None, **kwargs) -> Any:
        # TODO via get_objects?
        raise NotImplementedError

    def view_url(self, object_id: str) -> str:
        # TODO 
        raise NotImplementedError

    def get_object(self, object_id: str, x_fields: str = None):
        
        headers = {}
        if x_fields:
            headers["X-Fields"] = x_fields

        return self.request(
            endpoint=f"objects/{object_id}",
            headers = headers
        )

    def get_classifiers(self, x_fields: str = None):
        
        headers = {}
        if x_fields:
            headers["X-Fields"] = x_fields

        return self.request(
            endpoint="classifiers/",
            headers = headers
        )

    def get_classifier_classes(self, classifier_name: str, classifier_version:str, x_fields: str = None):
        
        headers = {}
        if x_fields:
            headers["X-Fields"] = x_fields

        return self.request(
            endpoint=f"classifiers/{classifier_name}/{classifier_version}/classes",
            headers = headers
        )

    def get_features(self, object_id: str, fid: int = None, version: str = None, x_fields: str = None):
        
        params = {}
        headers = {}
        
        if fid:
            params["fid"] = fid
        if version:
            params["version"] = version
        if x_fields:
            headers["X-Fields"] = x_fields

        return self.request(
            endpoint=f"objects/{object_id}/features",
            params = params,
            headers = headers
        )

    def get_feature_name(self, object_id: str, name: str, fid: int = None, version: str = None, x_fields: str = None):
        
        params = {}
        headers = {}
        
        if fid:
            params["fid"] = fid
        if version:
            params["version"] = version
        if x_fields:
            headers["X-Fields"] = x_fields

        return self.request(
            endpoint=f"objects/{object_id}/features/{name}",
            params = params,
            headers = headers
        )

    def get_lightcurve(self, object_id: str):
        endpoint = f"objects/{object_id}/lightcurve"
        return self.request(endpoint)

    def get_lightcurve_detections(self, object_id: str):
        endpoint = f"objects/{object_id}/lightcurve/detections"
        return self.request(endpoint)

    def get_lightcurve_non_detections(self, object_id: str):
        endpoint = f"objects/{object_id}/lightcurve/non_detections"
        return self.request(endpoint)

    def get_objects(
        self,
        oid: Union[str, List[str]] = None,
        classifier: str = None,
        classifier_version: str = None,
        class_name: str = None,  # Using class_name to avoid Python keyword conflict
        ranking: int = 1,
        ndet: Union[int, List[int]] = None,
        probability: float = None,
        firstmjd: Union[float, List[float]] = None,
        lastmjd: Union[float, List[float]] = None,
        ra: float = None,
        dec: float = None,
        radius: float = 30.0,
        page: int = None,
        page_size: int = None,
        count: bool = None,
        order_by: str = None,
        order_mode: str = None,
        x_fields: str = None
    ):
        """
        Retrieve objects from ALeRCE database with filtering and pagination.

        Parameters:
        - oid (str|list): Object ID(s)
        - classifier (str): Classifier name
        - classifier_version (str): Classifier version
        - class_name (str): Class name
        - ranking (int): Class ordering by probability (default: 1)
        - ndet (int|list): Detection count or range [min, max]
        - probability (float): Minimum probability
        - firstmjd (float|list): First detection MJD or range [min, max]
        - lastmjd (float|list): Last detection MJD or range [min, max]
        - ra (float): RA for conesearch (degrees)
        - dec (float): Dec for conesearch (degrees)
        - radius (float): Conesearch radius (arcsec, default: 30)
        - page (int): Page number for pagination
        - page_size (int): Items per page
        - count (bool): Whether to count total objects
        - order_by (str): Column for ordering results
        - order_mode (str): Order direction ('asc' or 'desc')
        - x_fields (str): Fields mask for header

        Returns:
        - Paginated list of objects matching criteria
        """
        params = {}
        headers = {}
        
        # Handle array parameters
        array_params = {
            "oid": oid,
            "ndet": ndet,
            "firstmjd": firstmjd,
            "lastmjd": lastmjd
        }
        
        for key, value in array_params.items():
            if value is not None:
                if isinstance(value, list):
                    params[key] = ",".join(map(str, value))
                else:
                    params[key] = str(value)
        
        # Handle single-value parameters
        if classifier:
            params["classifier"] = classifier
        if classifier_version:
            params["classifier_version"] = classifier_version
        if class_name:
            params["class"] = class_name
        if ranking is not None:
            params["ranking"] = str(ranking)
        if probability is not None:
            params["probability"] = str(probability)
        if ra is not None:
            params["ra"] = str(ra)
        if dec is not None:
            params["dec"] = str(dec)
        if radius is not None:
            params["radius"] = str(radius)
        if page is not None:
            params["page"] = str(page)
        if page_size is not None:
            params["page_size"] = str(page_size)
        if count is not None:
            params["count"] = str(count).lower()
        if order_by:
            params["order_by"] = order_by
        if order_mode:
            params["order_mode"] = order_mode
        if x_fields:
            headers["X-Fields"] = x_fields
        
        return self.request(endpoint="objects/", params=params, headers=headers)
