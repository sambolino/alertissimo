"""Architecture and behavior contracts for generic request-side transforms."""

import subprocess
import sys
from pathlib import Path

import pytest

from alertissimo.data_layer.execution import EndpointRegistry
from alertissimo.data_layer.transforms.request import (
    apply_binding_adapter,
    RequestTransformError,
    UnsupportedRequestTransformError,
    coerce_physical_type,
    load_binding_adapter,
    transform_collection,
)
from alertissimo.data_layer.transforms.sql import string_membership_condition


ROOT = Path(__file__).parents[1]


def test_request_transform_layer_is_provider_neutral():
    source = (
        ROOT / "alertissimo" / "data_layer" / "transforms" / "request.py"
    ).read_text(encoding="utf-8").lower()
    for provider in ("alerce", "antares", "fink", "lasair"):
        assert provider not in source
    assert "import importlib" not in source


def test_astropy_transform_is_generic_not_antares_specific():
    source = (
        ROOT / "alertissimo" / "data_layer" / "transforms" / "astropy.py"
    ).read_text(encoding="utf-8").lower()
    assert "antares" not in source
    assert not (
        ROOT / "alertissimo" / "data_layer" / "providers" / "antares_binding.py"
    ).exists()


def test_binder_keeps_generic_request_conversion_outside_orchestration():
    source = (
        ROOT / "alertissimo" / "orchestration" / "binding" / "binder.py"
    ).read_text(encoding="utf-8")
    assert "import importlib" not in source
    assert 'collection == "csv"' not in source
    assert "int(value)" not in source
    assert "float(value)" not in source


def test_antares_cone_declares_generic_astropy_transform_paths():
    registry = EndpointRegistry()
    for origin in ("lsst", "ztf"):
        spec = registry.resolve("antares", origin, "cone_search")
        assert spec.params["center"]["binding"]["adapter"].startswith(
            "alertissimo.data_layer.transforms."
        )
        assert spec.params["radius"]["binding"]["adapter"].startswith(
            "alertissimo.data_layer.transforms."
        )


def test_unregistered_provider_adapter_is_rejected():
    with pytest.raises(RequestTransformError, match="not a registered request transform"):
        load_binding_adapter(
            "alertissimo.data_layer.providers.antares_binding:skycoord_icrs_degrees"
        )


def test_generic_collection_and_scalar_request_transforms():
    assert transform_collection(
        ["A", "B"],
        {"binding": {"collection": "csv", "max_items": 2}},
        role="target_id",
    ) == "A,B"
    assert coerce_physical_type("123", {"type": "integer"}, role="target_id") == 123
    assert coerce_physical_type(3, {"type": "number"}, role="radius") == 3.0


def test_generic_sql_membership_transform_uses_validated_adapter_options():
    path = "alertissimo.data_layer.transforms.sql:string_membership_condition"
    options = {
        "column": "objects.objectId",
        "value_pattern": r"^ZTF\d{2}[a-z]{7}$",
    }

    assert apply_binding_adapter(
        path,
        {"target_id": ("ZTF20acpwljl", "ZTF21abfmbix")},
        options=options,
    ) == 'objects.objectId IN ("ZTF20acpwljl","ZTF21abfmbix")'


@pytest.mark.parametrize(
    ("column", "target_id", "match"),
    [
        ("objects.objectId; DROP TABLE objects", "ZTF20acpwljl", "column"),
        ("objects.objectId", 'ZTF20acpwljl" OR 1=1', "values"),
        ("objects.objectId", (), "at least one"),
    ],
)
def test_generic_sql_membership_transform_rejects_unsafe_fragments(
    column, target_id, match
):
    with pytest.raises(ValueError, match=match):
        string_membership_condition(
            target_id,
            column=column,
            value_pattern=r"^ZTF\d{2}[a-z]{7}$",
        )


def test_generic_singular_cardinality_rejection_stays_outside_orchestration():
    with pytest.raises(UnsupportedRequestTransformError, match="cardinality 2"):
        transform_collection(["A", "B"], {}, role="target_id")


def test_generic_type_coercion_raises_generic_transform_error():
    with pytest.raises(RequestTransformError, match="declares type 'integer'"):
        coerce_physical_type(
            "not-an-integer", {"type": "integer"}, role="target_id"
        )


def test_generic_request_transform_package_imports_without_astropy():
    code = """
import sys
sys.modules['astropy'] = None
sys.modules['astropy.coordinates'] = None
sys.modules['astropy.units'] = None
from alertissimo.data_layer.transforms import request
from alertissimo.data_layer.transforms import astropy as astropy_transforms
assert callable(request.transform_collection)
assert callable(astropy_transforms.skycoord_icrs_degrees)
assert callable(astropy_transforms.angle_arcsec)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
