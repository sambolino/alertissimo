import pytest

from alertissimo.data_layer.runtime.payload_paths import extract_raw_field, resolve_payload_items


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


def test_dictionary_expansion_preserves_keys_values_and_list_indexes():
    items = resolve_payload_items(
        {"classifications": {"ZTF20acpwljl": ["SN", "description"]}},
        payload_key="sherlock_position_classifications",
        payload_path="classifications{}",
    )
    assert items[0].value == {
        "_key": "ZTF20acpwljl", "_value": ["SN", "description"],
    }
    assert extract_raw_field(items[0].value, "_value.0") == "SN"
    assert extract_raw_field(items[0].value, "_value.1") == "description"


def test_missing_and_structural_mismatches_are_empty():
    assert resolve_payload_items({}, payload_key="x", payload_path="missing[]") == ()
    assert resolve_payload_items({"rows": {}}, payload_key="x", payload_path="rows[]") == ()
    assert resolve_payload_items({}, payload_key="x", payload_path="[]") == ()


@pytest.mark.parametrize("path", ["", "candidates", ".candidates[]", "a[].b[]", "[]candidates[]"])
def test_invalid_syntax_raises(path):
    with pytest.raises(ValueError):
        resolve_payload_items({}, payload_key="x", payload_path=path)
