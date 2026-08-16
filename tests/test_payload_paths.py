import pytest

from alertissimo.data_layer.runtime.payload_paths import (
    RawFieldMissing,
    extract_raw_field,
    resolve_payload_items,
)


def test_root_singleton():
    payload = {"value": 1}
    items = resolve_payload_items(payload, payload_key="object", payload_path=".")
    assert len(items) == 1
    assert items[0].value is payload
    assert items[0].payload_index is None
    assert items[0].index_path == ()


def test_root_list():
    items = resolve_payload_items(["a", "b"], payload_key="rows", payload_path="[]")
    assert [item.value for item in items] == ["a", "b"]
    assert [item.payload_index for item in items] == [0, 1]
    assert [item.index_path for item in items] == [(0,), (1,)]


@pytest.mark.parametrize(
    ("path", "payload", "expected"),
    [
        ("candidates[]", {"candidates": [1, 2]}, [1, 2]),
        ("catalog_objects.allwise[]", {"catalog_objects": {"allwise": [3]}}, [3]),
        ("alerts[]", {"alerts": [4]}, [4]),
    ],
)
def test_mapping_list_paths(path, payload, expected):
    items = resolve_payload_items(payload, payload_key="rows", payload_path=path)
    assert [item.value for item in items] == expected


def test_nested_root_list_preserves_index_path_and_flattens_index():
    payload = [{"candidates": ["a", "b", "c"]}, {"candidates": ["d"]}]
    items = resolve_payload_items(payload, payload_key="candidate", payload_path="[].candidates[]")
    assert [item.value for item in items] == ["a", "b", "c", "d"]
    assert [item.payload_index for item in items] == [0, 1, 2, 3]
    assert [item.index_path for item in items] == [(0, 0), (0, 1), (0, 2), (1, 0)]


def test_mapping_expansion_is_sorted_by_key():
    payload = {
        "classifications": {
            "ZTF20b": ["AGN", "likely"],
            "ZTF20a": ["SN", "description"],
        }
    }
    items = resolve_payload_items(
        payload, payload_key="classifications", payload_path="classifications{}"
    )
    assert [item.value for item in items] == [
        {"_key": "ZTF20a", "_value": ["SN", "description"]},
        {"_key": "ZTF20b", "_value": ["AGN", "likely"]},
    ]
    assert [item.index_path for item in items] == [(0,), (1,)]


def test_mapping_expansion_below_root_list():
    payload = [
        {"classifications": {"ZTF20b": ["AGN", "likely"]}},
        {"classifications": {"ZTF20a": ["SN", "description"]}},
    ]
    items = resolve_payload_items(
        payload, payload_key="classifications", payload_path="[].classifications{}"
    )
    assert [item.value["_key"] for item in items] == ["ZTF20b", "ZTF20a"]
    assert [item.index_path for item in items] == [(0, 0), (1, 0)]


def test_extract_raw_field_supports_list_indexes():
    record = {"_key": "ZTF20a", "_value": ["SN", "description"]}
    assert extract_raw_field(record, "_key") == "ZTF20a"
    assert extract_raw_field(record, "_value.0") == "SN"
    assert extract_raw_field(record, "_value.1") == "description"
    with pytest.raises(RawFieldMissing):
        extract_raw_field(record, "_value.2")


def test_missing_and_structural_mismatches_are_empty():
    assert resolve_payload_items({}, payload_key="x", payload_path="missing[]") == ()
    assert resolve_payload_items({"rows": {}}, payload_key="x", payload_path="rows[]") == ()
    assert resolve_payload_items({}, payload_key="x", payload_path="[]") == ()


@pytest.mark.parametrize(
    "path",
    ["", "candidates", ".candidates[]", "a[].b[]", "[]candidates[]", "a{}.b{}"],
)
def test_invalid_syntax_raises(path):
    with pytest.raises(ValueError):
        resolve_payload_items({}, payload_key="x", payload_path=path)


def test_nested_root_expansion_retains_corresponding_root_object():
    payload = [
        {"objectId": "A", "candidates": [{"candid": 1}]},
        {"objectId": "B", "candidates": [{"candid": 2}, {"candid": 3}]},
    ]
    items = resolve_payload_items(payload, payload_key="candidates", payload_path="[].candidates[]")
    assert [item.root_value["objectId"] for item in items] == ["A", "B", "B"]
    assert [item.index_path for item in items] == [(0, 0), (1, 0), (1, 1)]
