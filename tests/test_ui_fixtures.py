from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from scripts.build_ui_fixtures import SPECS, build_corpus, portfolio_families

EXPECTED = set(SPECS) | {
    "multibroker_lsst_170587117485817955.json",
    "multisurvey_fink_313936986529333309__ZTF18acurdih.json",
    "minimal_summary_real.json", "minimal_detection_real.json",
    "semantic_gallery_synthetic.json",
}


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    path = tmp_path_factory.mktemp("ui-portfolios")
    build_corpus(path)
    return path


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_complete_portfolio_only_corpus(generated):
    assert {p.name for p in generated.glob("*.json")} == EXPECTED
    for path in generated.glob("*.json"):
        assert set(_load(path)) == {"internal_portfolio_id", "executions", "records", "edges"}


def test_deterministic(tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"
    build_corpus(one)
    build_corpus(two)
    assert {p.name: p.read_bytes() for p in one.iterdir()} == {
        p.name: p.read_bytes() for p in two.iterdir()}


def test_all_real_provider_survey_pairs_exist(generated):
    names = {p.name for p in generated.glob("*.json")}
    for broker in ("alerce", "antares", "fink", "lasair"):
        assert any(n.startswith(f"lsst_{broker}_") for n in names)
        assert any(n.startswith(f"ztf_{broker}_") for n in names)


def test_composed_objects_preserve_provenance_and_native_ids(generated):
    multi = _load(generated / "multibroker_lsst_170587117485817955.json")
    assert {e["broker"] for e in multi["executions"]} == {"alerce", "fink", "antares"}
    assert "170587117485817955" in json.dumps(multi)
    surveys = _load(generated / "multisurvey_fink_313936986529333309__ZTF18acurdih.json")
    assert {e["origin"] for e in surveys["executions"]} == {"lsst", "ztf"}
    text = json.dumps(surveys)
    assert "313936986529333309" in text and "ZTF18acurdih" in text


def test_minimal_portfolios(generated):
    for name, family in (("minimal_summary_real.json", "summary"),
                         ("minimal_detection_real.json", "detection")):
        records = _load(generated / name)["records"]
        assert len(records) == 1
        assert records[0]["semantic_type"].split("@", 1)[0] == family


def test_every_semantic_family_supports_detail_and_group(generated):
    per_file = []
    for path in generated.glob("*.json"):
        per_file.append(Counter(r["semantic_type"].split("@", 1)[0] for r in _load(path)["records"]))
    for family in portfolio_families():
        assert sum(c[family] for c in per_file) >= 1
        assert any(c[family] >= 2 for c in per_file)


def test_real_summary_search_coverage(generated):
    real_names = set(SPECS)
    assert sum(any(r["semantic_type"].startswith("summary@") for r in
                   _load(generated / name)["records"]) for name in real_names) >= 8


def test_lightcurve_projection(generated):
    pytest.importorskip("pandas")
    from alertissimo.data_layer.presentation.portfolio_lightcurve import serialized_portfolio_lightcurve_dataframe
    for name in ("lsst_lasair_313761042336317573.json", "ztf_alerce_ZTF18abbuksn.json",
                 "multisurvey_fink_313936986529333309__ZTF18acurdih.json"):
        assert not serialized_portfolio_lightcurve_dataframe(_load(generated / name)).empty


def test_internal_identifier_and_provenance_integrity(generated):
    for path in generated.glob("*.json"):
        data = _load(path)
        record_ids = [r["internal_record_id"] for r in data["records"]]
        execution_ids = [e["internal_execution_id"] for e in data["executions"]]
        edge_ids = [e["internal_edge_id"] for e in data["edges"]]
        assert len(record_ids) == len(set(record_ids))
        assert len(execution_ids) == len(set(execution_ids))
        assert len(edge_ids) == len(set(edge_ids))
        for record in data["records"]:
            if record["internal_source"]:
                assert record["internal_source"]["internal_execution_id"] in execution_ids
        for edge in data["edges"]:
            assert edge["subject_record_id"] in record_ids
            assert edge["target_record_id"] in record_ids
