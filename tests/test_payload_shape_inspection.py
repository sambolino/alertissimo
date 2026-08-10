import json
import subprocess
import sys

from tools.inspect_payload_shape import describe_payload


def test_shape_describes_nested_lists_deterministically():
    payload = {"crossmatches": [{"name": "source", "redshift": None}], "classifications": {"ZTF1": ["SN"]}}
    lines = describe_payload(payload)
    text = "\n".join(lines)
    assert lines[:2] == ["top-level type: object", "top-level keys: classifications, crossmatches"]
    assert "crossmatches: list[1]" in text
    assert "crossmatches[] object key sample: name, redshift" in text
    assert "redshift: null" in text


def test_shape_cli_options_limit_list_samples(tmp_path):
    path = tmp_path / "payload.json"
    path.write_text(json.dumps({"items": [{"a": 1}, {"b": 2}]}), encoding="utf-8")
    result = subprocess.run([sys.executable, "tools/inspect_payload_shape.py", str(path), "--depth", "2", "--max-list-items", "1"], check=True, capture_output=True, text=True)
    assert "items: list[2]" in result.stdout
    assert "items[] object key sample: a" in result.stdout
    assert "items[1]" not in result.stdout
