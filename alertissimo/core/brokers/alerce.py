"""ALeRCE adapter backed by the official ALeRCE Python Client."""

from typing import Any, Iterator, List, Optional

from alerce.core import Alerce

from .base import Broker


class ALeRCEBroker(Broker):
    """Expose the project's Broker interface through ALeRCE Client 2.x.

    ALeRCE Client routes ZTF object, detection, and lightcurve queries to its
    supported ZTF API, and additionally exposes the v2 forced-photometry and
    ZTF AVRO stamp services.  The adapter keeps Alertissimo's existing method
    names while making those two data products available as well.
    """

    survey = "ztf"

    def __init__(self) -> None:
        super().__init__(
            name="ALeRCE",
            base_url="https://api.alerce.online/ztf/v1",
        )
        self.client = Alerce()

    def is_available(self) -> bool:
        # The public ALeRCE APIs used by this adapter require no credentials.
        return True

    def normalize_object(
        self,
        raw_data: Optional[dict],
        include_summary: bool = False,
        include_raw: bool = False,
    ) -> dict:
        if not raw_data:
            return {}

        result: dict[str, Any] = {}
        if include_summary:
            result["summary"] = raw_data
        if include_raw:
            result["raw"] = raw_data
        return result

    def conesearch(self, ra: float, dec: float, radius: float, **kwargs) -> Any:
        return self.client.query_objects(
            survey=self.survey,
            ra=ra,
            dec=dec,
            radius=radius,
            format=kwargs.pop("format", "json"),
            **kwargs,
        )

    def findobject(self, object_id: str, **kwargs) -> Any:
        raw_data = self.client.query_object(
            object_id,
            survey=self.survey,
            format=kwargs.pop("format", "json"),
            **kwargs,
        )
        return self.normalize_object(raw_data, include_summary=True)

    def findobjects(
        self, object_ids: Optional[List[str]], **kwargs
    ) -> Iterator[Any]:
        return self.client.query_objects(
            oid=object_ids,
            survey=self.survey,
            format=kwargs.pop("format", "json"),
            **kwargs,
        )

    def lightcurve(self, object_id: str, **kwargs) -> Any:
        return self.client.query_lightcurve(
            object_id,
            survey=self.survey,
            format=kwargs.pop("format", "json"),
        )

    def classify(self, object_id: str, **kwargs) -> Any:
        return self.client.query_probabilities(
            object_id,
            survey=self.survey,
            format=kwargs.pop("format", "json"),
            **kwargs,
        )

    def forced_photometry(self, object_id: str, **kwargs) -> Any:
        """Retrieve ZTF forced photometry from ALeRCE's v2 endpoint."""
        return self.client.query_forced_photometry(
            object_id,
            survey=self.survey,
            format=kwargs.pop("format", "json"),
        )

    def cutout(self, object_id: str, **kwargs) -> Any:
        """Retrieve the science, template, and difference stamp triplet."""
        return self.client.get_stamps(
            object_id,
            candid=kwargs.pop("candid", None),
            measurement_id=kwargs.pop("measurement_id", None),
            survey=self.survey,
            format=kwargs.pop("format", "numpy"),
        )

    # Compatibility helpers for callers that used the prior private methods.
    def _object(self, object_id: str, **kwargs) -> Any:
        return self.client.query_object(object_id, survey=self.survey, **kwargs)

    def _objects(self, oid: Optional[List[str]] = None, **kwargs) -> Any:
        return self.client.query_objects(oid=oid, survey=self.survey, **kwargs)

    def _lightcurve(self, object_id: str) -> Any:
        return self.client.query_lightcurve(object_id, survey=self.survey)

    def _lightcurve_detections(self, object_id: str) -> Any:
        return self.client.query_detections(object_id, survey=self.survey)

    def _lightcurve_non_detections(self, object_id: str) -> Any:
        return self.client.query_non_detections(object_id, survey=self.survey)

    def _features(self, object_id: str, **kwargs) -> Any:
        return self.client.query_features(object_id, survey=self.survey, **kwargs)

    def _feature_name(self, object_id: str, name: str, **kwargs) -> Any:
        return self.client.query_feature(object_id, name, survey=self.survey, **kwargs)

    def _classifiers(self, **kwargs) -> Any:
        return self.client.query_classifiers(survey=self.survey, **kwargs)

    def _classifier_classes(
        self, classifier_name: str, classifier_version: str, **kwargs
    ) -> Any:
        return self.client.query_classes(
            classifier_name,
            classifier_version,
            survey=self.survey,
            **kwargs,
        )
