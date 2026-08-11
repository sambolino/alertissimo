import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
ENDPOINTS = ROOT / "alertissimo/data_layer/providers/alerce/ztf/endpoints.yaml"
QUERY_OBJECTS_FIXTURE = ROOT / "tests/fixtures/alerce/ztf/query_objects.json"


def test_query_objects_pagination_scalars_are_nullable_integers():
    endpoints = yaml.safe_load(ENDPOINTS.read_text(encoding="utf-8"))
    pagination = endpoints["endpoints"]["query_objects"]["output"]["pagination"]
    payload = json.loads(QUERY_OBJECTS_FIXTURE.read_text(encoding="utf-8"))

    for field in ("total", "page", "next", "prev"):
        assert pagination[field]["type"] == "integer"
        assert pagination[field]["nullable"] is True
        assert payload[field] is None
