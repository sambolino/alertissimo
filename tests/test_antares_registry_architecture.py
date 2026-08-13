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
    assert lsst["mappings"]["detection@lsst:antares.time.mjd"] == ["locus_alerts#properties.lsst_diaSource_midpointMjdTai"]
    assert lsst["transforms"]["detection@lsst:antares.image_metrics.is_positive"]["locus_alerts#properties.lsst_diaSource_isNegative"]["type"] == "boolean_not"
    ztf = load("ztf", "mappings.yaml")
    assert ztf["transforms"]["detection@ztf:antares.image_metrics.is_positive"]["locus_alerts#properties.ztf_isdiffpos"]["type"] == "value_map"


class FakeAlert:
    def __init__(self, alert_id, mjd, properties):
        self.alert_id, self.mjd, self.properties = alert_id, mjd, properties

class FakeLocus:
    def __init__(self):
        self.locus_id, self.ra, self.dec = "ANT2020nb5h6", 50.8, 37.4
        self.properties = {"ztf_object_id": "ZTF20aafqubg"}
        self.alerts = [FakeAlert("ztf_candidate:1", 60000.0, {"ztf_candid": 1})]
        self.catalog_objects = {"gaia_dr3_gaia_source": [{"source_id": 123, "parallax": 1.2}]}

def test_python_client_model_payload_refs_resolve():
    from alertissimo.data_layer.runtime.payload_paths import extract_raw_field, resolve_payload_items
    locus=FakeLocus()
    assert extract_raw_field(locus, "properties.ztf_object_id") == "ZTF20aafqubg"
    alerts=resolve_payload_items(locus,payload_key="alerts",payload_path="alerts[]")
    assert extract_raw_field(alerts[0].value,"properties.ztf_candid")==1
    gaia=resolve_payload_items(locus,payload_key="gaia",payload_path="catalog_objects.gaia_dr3_gaia_source[]")
    assert extract_raw_field(gaia[0].value,"parallax")==1.2

def test_private_or_callable_attributes_are_not_payload_data():
    from alertissimo.data_layer.runtime.payload_paths import RawFieldMissing, extract_raw_field
    locus=FakeLocus()
    with pytest.raises(RawFieldMissing): extract_raw_field(locus,"__dict__")
    with pytest.raises(RawFieldMissing): extract_raw_field(locus,"alerts.append")
