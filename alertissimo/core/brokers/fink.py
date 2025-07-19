# alertissimo/core/brokers/fink.py
from .base import Broker
from typing import Union, List, Optional, Iterator, Any

class FinkBroker(Broker):
    def __init__(self):
        super().__init__(
            name="Fink",
            base_url="https://api.fink-portal.org/api/v1"
        )

# cutouts,latests,anomaly,stats,classes etc 


    def is_available(self) -> bool:
        # Fink REST api is publicly available without credentials
        return True

    def conesearch(self, ra: float, dec: float, radius: float, **kwargs) -> Any:
        return self.get_conesearch(ra, dec, radius, **kwargs)

    def object_query(self, object_id: str, **kwargs) -> Any:
        return self.get_object(object_id, **kwargs)

    def objects_query(self, object_ids: List[str], **kwargs) -> Iterator[Any]:
        return self.get_object(object_id=object_ids, **kwargs)

    def sql_query(self, query: str, **kwargs) -> Iterator[Any]:
        raise NotImplementedError

    def kafka_stream(self, **kwargs) -> Iterator[Any]:
        raise NotImplementedError

    def lightcurve(self, object_id: str, **kwargs) -> Any:
        # TODO
        raise NotImplementedError

    def classifications(self, object_id: str, **kwargs) -> Any:
        # TODO
        raise NotImplementedError

    def forced_photometry(self, ra: float, dec: float, jd: float, **kwargs) -> Any:
        # TODO
        raise NotImplementedError

    def crossmatch(self, object_id: str, catalog: Optional[str] = None, **kwargs) -> Any:
        # TODO
        raise NotImplementedError

    def view_url(self, object_id: str) -> str:
        # TODO
        raise NotImplementedError

    def get_object(
        self,
        object_id: Union[str, List[str]],
        withupperlim: bool = False,
        withcutouts: bool = False,
        cutout_kind: str = None,
        columns: str = None,
        output_format: str = "json"
    ):
        """
        Retrieve data for one or more ZTF object IDs.

        Parameters:
        - object_id (str): ZTF ID or comma-separated list of IDs
        - withupperlim (bool): Include upper limits and bad quality measurements
        - withcutouts (bool): Include 2D image cutouts
        - cutout_kind (str): 'Science', 'Template', or 'Difference'
        - columns (str): Comma-separated data columns (e.g., 'i:magpsf,i:jd')
        - output_format (str): 'json', 'csv', 'parquet', or 'votable'

        Returns:
        - dict or list depending on output format
        """
        params = {
            "objectId": object_id,
            "output-format": output_format
        }

        if withupperlim:
            params["withupperlim"] = "True"

        if withcutouts:
            params["withcutouts"] = "True"

        if cutout_kind:
            params["cutout-kind"] = cutout_kind

        if columns:
            params["columns"] = columns

        return self.request("objects", params=params)

    def get_cutouts(
        self,
        object_id: str,
        kind: str = "Science",
        output_format: str = "PNG",
        candid: str = None,
        stretch: str = "sigmoid",
        colormap: str = "grayscale",
        pmin: str = "0.5",
        pmax: str = "99.5",
        convolution_kernel: str = None
    ):
        """
        Retrieve image cutouts for a ZTF object.

        Parameters:
        - object_id (str): ZTF Object ID
        - kind (str): 'Science', 'Template', 'Difference', or 'All'
        - output_format (str): 'PNG' (default), 'FITS', or 'array'
        - candid (str): Candidate ID. If not provided, gets latest alert
        - stretch (str): Stretch function ('sigmoid', 'linear', etc.)
        - colormap (str): Matplotlib colormap name (default: 'grayscale')
        - pmin (str): Min cut level percentile (default: 0.5)
        - pmax (str): Max cut level percentile (default: 99.5)
        - convolution_kernel (str): Convolve the image with a kernel (gauss or box)

        Returns:
        - Dict or image data depending on output format
        """
        params = {
            "objectId": object_id,
            "kind": kind,
            "output-format": output_format,
            "stretch": stretch,
            "colormap": colormap,
            "pmin": pmin,
            "pmax": pmax
        }

        if candid:
            params["candid"] = candid

        if convolution_kernel:
            params["convolution_kernel"] = convolution_kernel

        return self.request("cutouts", params=params)

    def get_latest_alerts(
        self,
        fink_class: str,
        trend: str = None,
        n: int = 100,
        startdate: str = "2019-11-01 00:00:00",
        stopdate: str = None,
        color: bool = False,
        columns: str = None,
        output_format: str = "json"
    ):
        """
        Retrieve latest alerts based on Fink class.

        Parameters:
        - fink_class (str): Fink derived class label (see `/api/v1/classes`)
        - trend (str): 'rising', 'fading', 'low_state', 'new_low_state' (optional)
        - n (int): Number of alerts (default: 100)
        - startdate (str): Start UTC date (iso, jd, or MJD)
        - stopdate (str): Stop UTC date (optional, default: now)
        - color (bool): If True, extract color info
        - columns (str): Comma-separated columns to return (optional)
        - output_format (str): One of 'json', 'csv', 'parquet', 'votable'

        Returns:
        - List or DataFrame of latest alerts
        """
        params = {
            "class": fink_class,
            "n": str(n),
            "startdate": startdate,
            "color": str(color).lower(),
            "output-format": output_format
        }

        if trend:
            params["trend"] = trend
        if stopdate:
            params["stopdate"] = stopdate
        if columns:
            params["columns"] = columns

        return self.request("latests", params=params)

    def get_class_labels(self):
        """
        Retrieve all Fink-derived class names and their origin.

        Returns:
        - List or DataFrame with class names and origins
        """
        return self.request("classes")

    def get_schema(self):
        """
        Get the data schema

        Returns:
        - dict of schema
        """
        return self.request("classes")

    
    def get_conesearch(
        self,
        ra: float,
        dec: float,
        radius: float,
        n: int = 1000,
        startdate: str = "2019-11-01 00:00:00",
        stopdate: str = None,
        window: str = None,
        columns: str = None,
        output_format: str = "json"
    ):
        """
        Perform a cone search around given coordinates.

        Parameters:
        - ra (float): Right Ascension in decimal degrees
        - dec (float): Declination in decimal degrees
        - radius (float): Search radius in arcseconds (max 18000 = 5 degrees)
        - n (int): Max number of alerts to return (default: 1000)
        - startdate (str): Start UTC date (iso, jd, or MJD) for first detection
        - stopdate (str): Stop UTC date (optional, default: now) for first detection
        - window (str): Time window in days (alternative to stopdate)
        - columns (str): Comma-separated columns to return (optional)
        - output_format (str): One of 'json', 'csv', 'parquet', 'votable'

        Returns:
        - List or DataFrame of alerts within the search cone
        """
        params = {
            "ra": ra,          # No str() conversion needed
            "dec": dec,        # No str() conversion needed
            "radius": radius,  # No str() conversion needed
            "n": n,            # No str() conversion needed
            "startdate": startdate,
            "output-format": output_format
        }

        if stopdate:
            params["stopdate"] = stopdate
        if window:
            params["window"] = window
        if columns:
            params["columns"] = columns

        return self.request("conesearch", params=params)

    def get_sso_data(
        self,
        n_or_d: Union[str, List[str]],
        withEphem: bool = False,
        withResiduals: bool = False,
        withCutouts: bool = False,
        cutout_kind: str = None,
        columns: str = None,
        output_format: str = "json"
    ):
        """
        Retrieve solar system object (SSO) data.

        Parameters:
        - n_or_d (str|list): IAU number/designation or list of designations
          (e.g., '8467', '10P', '2010JO69', or ['C/2020V2', '2012LA'])
        - withEphem (bool): Attach Miriade ephemerides (default: False)
        - withResiduals (bool): Return obs-model residuals (only for single objects)
        - withCutouts (bool): Retrieve cutout data (default: False)
        - cutout_kind (str): Cutout type - 'Science', 'Template', or 'Difference'
        - columns (str): Comma-separated columns to return (optional)
        - output_format (str): Output format: 'json'[default], 'csv', 'parquet', 'votable'

        Returns:
        - Solar system object data in requested format

        Notes:
        - withResiduals only works for single object queries
        - Cutouts info: https://irsa.ipac.caltech.edu/data/ZTF/docs/ztf_explanatory_supplement.pdf
        """
        # Convert list of objects to comma-separated string
        if isinstance(n_or_d, list):
            n_or_d = ",".join(n_or_d)

        params = {
            "n_or_d": n_or_d,
            "withEphem": str(withEphem).lower(),
            "withResiduals": str(withResiduals).lower(),
            "withCutouts": str(withCutouts).lower(),
            "output-format": output_format
        }

        if cutout_kind:
            params["cutout-kind"] = cutout_kind
        if columns:
            params["columns"] = columns

        return self.request("sso", params=params)

    def get_ssocand(
        self,
        kind: str,
        ssoCandId: str = None,
        start_date: str = "2019-11-01",
        stop_date: str = None,
        maxnumber: int = 10000,
        output_format: str = "json"
    ):
        """
        Retrieve solar system candidate data (orbital parameters or lightcurves).

        Parameters:
        - kind (str): Data type - 'orbParams' (orbital parameters) or 'lightcurves'
        - ssoCandId (str): Specific trajectory ID (optional)
        - start_date (str): Start UTC date (YYYY-MM-DD) for lightcurves
        - stop_date (str): Stop UTC date (YYYY-MM-DD) for lightcurves (default: now)
        - maxnumber (int): Maximum entries to retrieve (default: 10000)
        - output_format (str): Output format: 'json'[default], 'csv', 'parquet', 'votable'

        Returns:
        - Solar system candidate data in requested format

        Notes:
        - start_date/stop_date only apply to kind='lightcurves'
        - If ssoCandId is not specified, returns all available candidates
        """
        params = {
            "kind": kind,
            "maxnumber": maxnumber,
            "output-format": output_format
        }

        if ssoCandId:
            params["ssoCandId"] = ssoCandId
        if kind == "lightcurves":
            params["start_date"] = start_date
            if stop_date:
                params["stop_date"] = stop_date

        return self.request("ssocand", params=params)

    def get_resolver(
        self,
        resolver: str,
        name: str,
        reverse: bool = False,
        nmax: int = 10,
        output_format: str = "json"
    ):
        """
        Resolve object names using external services.

        Parameters:
        - resolver (str): Name resolver service - 'simbad', 'ssodnet', or 'tns'
        - name (str): Object name to resolve
        - reverse (bool): If True, resolve ZTF names to external IDs (default: False)
        - nmax (int): Maximum number of matches to return (default: 10)
        - output_format (str): Output format: 'json'[default], 'csv', 'parquet', 'votable'

        Returns:
        - Resolution results in requested format
        """
        params = {
            "resolver": resolver,
            "name": name,
            "reverse": str(reverse).lower(),
            "nmax": nmax,
            "output-format": output_format
        }
        return self.request("resolver", params=params)

    def get_tracklet(
        self,
        date: str,
        tracklet_id: str = None,
        columns: str = None,
        output_format: str = "json"
    ):
        """
        Retrieve satellite and debris data by observation date or tracklet ID.

        Parameters:
        - date (str): Observation date in ISO format (YYYY-MM-DD [hh:mm:ss] or YYYY-MM-DD or YYYY-MM-DD hh)
        - tracklet_id (str): Tracklet ID (format: TRCK_YYYYMMDD_HHMMSS_NN)
        - columns (str): Comma-separated columns to return (optional)
        - output_format (str): Output format: 'json'[default], 'csv', 'parquet', 'votable'

        Returns:
        - Tracklet data in requested format

        Note: Either date or tracklet_id must be provided.
        """
        params = {
            "date": date,
            "output-format": output_format
        }

        if tracklet_id:
            params["id"] = tracklet_id
        if columns:
            params["columns"] = columns

        return self.request("tracklet", params=params)

    def post_skymap(
        self,
        credible_level: float,
        file: str = None,
        event_name: str = None,
        n_day_before: int = 1,
        n_day_after: int = 6,
        output_format: str = "json"
    ):
        # THIS SHOULD BE A POST REQUEST, WE MAY IMPLEMENT THIS AT SOME POINT 
        """
        curl -X 'POST' \
            'https://api.fink-portal.org/api/v1/skymap' \
            -H 'accept: application/json' \
            -H 'Content-Type: application/json' \
            -d '{
            "file": {},
            "event_name": "S230709bi",
            "credible_level": 0.1,
            "n_day_before": 1,
            "n_day_after": 6,
            "output-format": "json"
        }'

        Retrieve Fink/ZTF alerts within a GW skymap.

        Parameters:
        - credible_level (float): GW credible region threshold (0.0-1.0)
        - file (str): Path to gzipped FITS skymap (bayestar.fits.gz)
        - event_name (str): GraceDB event name (alternative to file)
        - n_day_before (int): Days to search before event (default: 1, max: 7)
        - n_day_after (int): Days to search after event (default: 6, max: 14)
        - output_format (str): Output format: 'json'[default], 'csv', 'parquet', 'votable'

        Returns:
        - Alerts within the GW skymap in requested format

        Notes:
        - Provide either file or event_name, but not both
        - Credible level: 0.0 (most probable) to 1.0 (least probable)
        - Searches within [-n_day_before, +n_day_after] days around event
        """
        if file and event_name:
            raise ValueError("Cannot specify both file and event_name")
        if not file and not event_name:
            raise ValueError("Must provide either file or event_name")

        params = {
            "credible_level": str(credible_level),
            "n_day_before": n_day_before,
            "n_day_after": n_day_after,
            "output-format": output_format
        }

        if file:
            params["file"] = file
        if event_name:
            params["event_name"] = event_name

        return None 
        #return self.request("skymap", params=params)

    def get_statistics(
        self,
        date: str = "",
        schema: bool = False,
        columns: str = None,
        output_format: str = "json"
    ):
        """
        Retrieve statistics about Fink and the ZTF alert stream.

        Parameters:
        - date (str): Observing date (YYYYMMDD for night, YYYYMM for month, 
                      YYYY for year, or empty string for everything). Default: "".
        - schema (bool): If True, return only the schema of statistics table. Default: False.
        - columns (str): Comma-separated columns to return (e.g., 'basic:sci,basic:date')
        - output_format (str): Output format: 'json'[default], 'csv', 'parquet', 'votable'

        Returns:
        - Statistics data in requested format
        """
        params = {
            "date": date,
            "schema": str(schema).lower(),
            "output-format": output_format
        }
        
        if columns:
            params["columns"] = columns
            
        return self.request("statistics", params=params)

    def get_anomaly(
        self,
        n: int = 10,
        start_date: str = "2019-11-01",
        stop_date: str = None,
        columns: str = None,
        output_format: str = "json"
    ):
        """
        Retrieve alerts tagged as anomalies from the Fink/ZTF database.

        Parameters:
        - n (int): Number of alerts to retrieve (most recent first). Default: 10.
        - start_date (str): Start UTC date (YYYY-MM-DD). Default: 2019-11-01.
        - stop_date (str): Stop UTC date (YYYY-MM-DD). Default: current datetime.
        - columns (str): Comma-separated columns to return (optional).
        - output_format (str): Output format: 'json'[default], 'csv', 'parquet', 'votable'.

        Returns:
        - Anomaly alerts in requested format

        Notes:
        - Alerts are returned in reverse chronological order (most recent first)
        - Time range is between start_date and stop_date
        """
        params = {
            "n": n,
            "start_date": start_date,
            "output-format": output_format
        }

        if stop_date:
            params["stop_date"] = stop_date
        if columns:
            params["columns"] = columns

        return self.request("anomaly", params=params)

    def get_ssoft(
        self,
        sso_name: str = None,
        sso_number: str = None,
        schema: bool = False,
        flavor: str = "SHG1G2",
        version: str = None,
        output_format: str = "parquet"
    ):
        """
        Retrieve Solar System Object Fink Table (SSoFT) data.

        Parameters:
        - sso_name (str): Official IAU name/provisional designation (optional)
        - sso_number (str): Official IAU number (optional)
        - schema (bool): Return table schema instead of data (default: False)
        - flavor (str): Data model - 'SSHG1G2', 'SHG1G2'[default], 'HG1G2', 'HG'
        - version (str): SSOFT version (YYYY.MM format, e.g., '2023.07')
        - output_format (str): Output format: 'parquet'[default], 'json', 'csv', 'votable'

        Returns:
        - SSoFT data in requested format

        Notes:
        - If neither sso_name nor sso_number specified, returns entire table
        - Latest version used when version is None
        - Data model options: SSHG1G2, SHG1G2, HG1G2, HG
        """
        params = {
            "schema": str(schema).lower(),
            "flavor": flavor,
            "output-format": output_format
        }

        if sso_name:
            params["sso_name"] = sso_name
        if sso_number:
            params["sso_number"] = sso_number
        if version:
            params["version"] = version

        return self.request("ssoft", params=params)
