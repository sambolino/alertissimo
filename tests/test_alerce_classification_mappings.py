from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).parents[1] / "alertissimo/core/brokers/registry/alerce"


def mappings(origin):
    return yaml.safe_load((ROOT / origin / "mappings.yaml").read_text(encoding="utf-8"))["mappings"]


@pytest.mark.parametrize("origin", ("lsst", "ztf"))
def test_mapping_blockers_remain_fixed(origin):
    entries = mappings(origin)
    paths = list(entries)
    references = [reference for refs in entries.values() for reference in refs]
    assert not any("step_id_corr" in value for value in paths + references)
    assert not any(".raw." in path for path in paths)
    assert not any(".classifier." in path for path in paths)
    assert f"classification@{origin}:alerce.ranking" not in entries
    assert not any(reference == "query_probabilities#ranking" for reference in references)
    for path, refs in entries.items():
        probability_refs = [ref for ref in refs if ref.startswith("query_probabilities#")]
        if probability_refs:
            assert path.startswith(f"classification@{origin}:alerce.assessment.{{output}}.")
    assert not any(
        reference.startswith("query_lightcurve#") and reference != "query_lightcurve#oid"
        for reference in references
    )
    assert not any(
        "#detections." in reference
        or "#forced_photometry." in reference
        or "#non_detections." in reference
        for reference in references
    )
