from tools.inspect_payload_shape import inspect_payload_shape


def test_inspection_describes_nested_objects_and_arrays():
    lines = inspect_payload_shape({"candidates": [{"candid": 1}]})
    assert "$: object (1 keys)" in lines
    assert "$.candidates: array (1 items)" in lines
    assert "$.candidates[0].candid: int" in lines
