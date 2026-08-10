from pathlib import Path

import pytest
import yaml

ROOT = Path("alertissimo/data_layer/providers/antares")
EXPECTED_ENDPOINTS = {
    "lsst": {"get_by_lsst_dia_object_id", "get_by_lsst_ss_object_id", "get_by_id", "cone_search", "search"},
    "ztf": {"get_by_ztf_object_id", "get_by_id", "cone_search", "search"},
}
FORBIDDEN_ENDPOINT_KEYS = {"provides", "output_type", "capabilities", "binding", "input", "value_from"}
ALLOWED_MAPPING_KEYS = {"broker", "origin", "payloads", "mappings", "transforms"}
OLD_REST_PATHS = {"/loci", "/loci/{locus_id}", "/alerts/{alert_id}/thumbnails"}


def load(origin, filename):
    return yaml.safe_load((ROOT / origin / filename).read_text(encoding="utf-8"))


@pytest.mark.parametrize("origin", EXPECTED_ENDPOINTS)
def test_python_client_endpoints(origin):
    endpoints = load(origin, "endpoints.yaml")["endpoints"]
    assert set(endpoints) == EXPECTED_ENDPOINTS[origin]
    for endpoint in endpoints.values():
        assert endpoint["method"] == "python"
        assert endpoint["path"].startswith("antares_client.search.")
        assert endpoint["path"] not in OLD_REST_PATHS
        assert not FORBIDDEN_ENDPOINT_KEYS & endpoint.keys()
        assert "survey" not in endpoint.get("params", {})
        assert endpoint["output"]["type"] in {"object_or_null", "iterator"}
        params = endpoint.get("params", {})
        assert set(endpoint.get("server_filters", [])) <= set(params)
        assert all(definition["description"].strip() for definition in params.values())


def test_no_extra_antares_registry_yaml_files():
    allowed = {"endpoints.yaml", "mappings.yaml", "unmapped_fields.yaml"}
    assert {path.name for path in ROOT.rglob("*.yaml")} <= allowed


@pytest.mark.parametrize("origin", EXPECTED_ENDPOINTS)
def test_minimal_mappings_and_payload_shapes(origin):
    document = load(origin, "mappings.yaml")
    endpoints = load(origin, "endpoints.yaml")["endpoints"]
    assert set(document) <= ALLOWED_MAPPING_KEYS
    mapped = set()
    for payload in document["payloads"].values():
        assert payload["endpoint"] in endpoints
        path = payload["path"]
        assert path in {".", "[]"} or path.endswith("[]")
        assert "row_filter" not in payload
    for refs in document["mappings"].values():
        assert isinstance(refs, list) and refs
        for ref in refs:
            payload, field = ref.split("#")
            assert payload in document["payloads"] and field
            mapped.add(ref)
    unmapped = load(origin, "unmapped_fields.yaml")["unmapped"]
    unmapped_refs = {next(iter(entry)) for entry in unmapped}
    assert mapped.isdisjoint(unmapped_refs)
    for semantic, specifications in document.get("transforms", {}).items():
        assert semantic in document["mappings"]
        assert set(specifications) <= set(document["mappings"][semantic])


def test_client_model_mapping_corrections_and_transforms():
    lsst = load("lsst", "mappings.yaml")
    assert lsst["mappings"]["detection@lsst:antares.identity.alert_id"] == ["locus_alerts#alert_id"]
    assert lsst["mappings"]["detection@lsst:antares.time.mjd"] == ["locus_alerts#mjd"]
    assert lsst["transforms"]["detection@lsst:antares.image_metrics.is_positive"]["locus_alerts#properties.lsst_diaSource_isNegative"]["type"] == "boolean_not"
    ztf = load("ztf", "mappings.yaml")
    assert ztf["transforms"]["detection@ztf:antares.image_metrics.is_positive"]["locus_alerts#properties.ztf_isdiffpos"]["type"] == "value_map"


class FakeAlert:
    def __init__(self, alert_id, mjd, properties):
        self.alert_id = alert_id
        self.mjd = mjd
        self.properties = properties


class FakeLocus:
    def __init__(self):
        self.locus_id = "ANT2026abc"
        self.ra = 123.4
        self.dec = -12.3
        self.properties = {"ztf_object_id": "ZTF20abc", "num_alerts": 2}
        self.tags = []
        self.alerts = [FakeAlert("alert1", 60000.0, {"ant_mag": 19.2, "ant_magerr": 0.1, "ztf_drb": 0.98, "ztf_isdiffpos": "t"})]
        self.catalog_objects = {
            "gaia_dr3_gaia_source": [{"object_id": "Gaia DR3 123", "properties": {"parallax": 1.2}}],
            "allwise": [{"object_id": "WISE 123", "properties": {"w1mpro": 15.1}}],
        }


def _field(value, path):
    for part in path.split("."):
        value = value[part] if isinstance(value, dict) else getattr(value, part)
    return value


def test_python_client_model_payload_refs_resolve():
    locus = FakeLocus()
    assert _field(locus, "properties.ztf_object_id") == "ZTF20abc"
    alert = locus.alerts[0]
    assert _field(alert, "mjd") == 60000.0
    assert _field(alert, "alert_id") == "alert1"
    assert _field(alert, "properties.ant_mag") == 19.2
    gaia = locus.catalog_objects["gaia_dr3_gaia_source"][0]
    allwise = locus.catalog_objects["allwise"][0]
    assert _field(gaia, "properties.parallax") == 1.2
    assert _field(allwise, "properties.w1mpro") == 15.1
