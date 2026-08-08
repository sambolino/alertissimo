import pytest

from alertissimo.core.brokers.registry.mapping_schema import validate_mapping_data


def valid_mapping(**updates):
    data = {
        "broker": "demo",
        "origin": "ztf",
        "mappings": {
            "summary@ztf:demo.identity.object_id": ["payload.objectId"],
        },
    }
    data.update(updates)
    return data


@pytest.mark.parametrize("field", ["broker", "origin"])
def test_required_identity_field_must_exist(field):
    data = valid_mapping()
    del data[field]

    with pytest.raises(ValueError, match=field):
        validate_mapping_data(data)


@pytest.mark.parametrize("field", ["broker", "origin"])
@pytest.mark.parametrize("value", ["", " \t\n"])
def test_required_identity_field_must_not_be_empty(field, value):
    with pytest.raises(ValueError, match=field):
        validate_mapping_data(valid_mapping(**{field: value}))


def test_empty_mapping_reference_list_is_rejected():
    data = valid_mapping(
        mappings={"summary@ztf:demo.identity.object_id": []},
    )

    with pytest.raises(ValueError, match="non-empty list"):
        validate_mapping_data(data)


@pytest.mark.parametrize("field", ["description", "notes"])
def test_optional_text_field_must_be_a_string(field):
    with pytest.raises(ValueError, match=field):
        validate_mapping_data(valid_mapping(**{field: ["not", "text"]}))


def test_optional_text_fields_accept_strings():
    validate_mapping_data(valid_mapping(description="A mapping", notes="A note"))
