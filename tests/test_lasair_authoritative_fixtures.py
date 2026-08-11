import json
from pathlib import Path

import yaml

from tools.audit_payload_mapping_coverage import audit_payload


FIXTURES = Path(__file__).parent / "fixtures" / "lasair" / "ztf"
PROVIDER = Path(__file__).parents[1] / "alertissimo/data_layer/providers/lasair/ztf"


def test_documented_cone_shape_uses_object_not_invented_summary_fields():
    payload = json.loads((FIXTURES / "cone.json").read_text())
    assert set(payload[0]) == {"object", "separation"}
    mappings = yaml.safe_load((PROVIDER / "mappings.yaml").read_text())
    refs = {ref for refs in mappings["mappings"].values() for ref in refs}
    assert "cone#object" in refs
    assert not {"cone#objectId", "cone#ramean", "cone#decmean"} & refs


def test_documented_cone_has_zero_unaccounted_leaves():
    payload = json.loads((FIXTURES / "cone.json").read_text())
    report = audit_payload(payload, broker="lasair", origin="ztf", endpoint="cone")
    assert "Observed leaves: 2" in report
    assert "Unaccounted leaves: 0" in report


def test_count_mode_is_a_separately_audited_shape():
    payload = json.loads((FIXTURES / "cone_count.json").read_text())
    report = audit_payload(payload, broker="lasair", origin="ztf", endpoint="cone")
    assert "Intentionally unmapped leaves: 1" in report
    assert "Unaccounted leaves: 0" in report
