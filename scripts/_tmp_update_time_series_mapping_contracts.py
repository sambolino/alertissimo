from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]


def replace_exact(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise RuntimeError(f"expected block not found in {path}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1))


# ---------------------------------------------------------------------------
# Account the deliberately deferred Fink fast-transient rate family as debt.
# ---------------------------------------------------------------------------
debt_path = ROOT / "alertissimo/data_layer/providers/fink/ztf/unmapped_fields.yaml"
debt = debt_path.read_text()
entries: list[tuple[str, str]] = []
for payload in ("objects", "sso", "latests", "anomaly"):
    for field, candidate in (
        ("d:mag_rate", "lightcurve@fink.magnitude_rate_points.photometry.{filter}.mag.rate"),
        ("d:sigma_rate", "lightcurve@fink.magnitude_rate_points.photometry.{filter}.mag.rate_error"),
        ("d:lower_rate", "lightcurve@fink.magnitude_rate_points.photometry.{filter}.mag.rate_lower_percentile"),
        ("d:upper_rate", "lightcurve@fink.magnitude_rate_points.photometry.{filter}.mag.rate_upper_percentile"),
    ):
        entries.append((f"{payload}#{field}", candidate))
for payload in ("sso", "latests", "anomaly"):
    entries.extend(
        (
            (f"{payload}#d:delta_time", "lightcurve@fink.magnitude_rate_points.time.delta"),
            (f"{payload}#d:from_upper", "lightcurve@fink.magnitude_rate_points.from_upper_limit"),
        )
    )

addition = ""
for raw_ref, candidate in entries:
    if f"- {raw_ref}:\n" in debt:
        continue
    addition += (
        f"- {raw_ref}:\n"
        "    reason: structural_multiplicity\n"
        "    note: Distinct Fink fast-transient magnitude-rate estimate is intentionally deferred until repeated rate-point collection can preserve it independently from query-time v:rate.\n"
        f"    candidate_meaning: {candidate}\n"
    )
if addition:
    if not debt.endswith("\n"):
        debt += "\n"
    debt_path.write_text(debt + addition)


# ---------------------------------------------------------------------------
# Update authoritative expectations to the new ontology/mapping contract.
# ---------------------------------------------------------------------------
fink_ztf = ROOT / "tests/test_fink_ztf_authoritative_payloads.py"
replace_exact(
    fink_ztf,
    '    assert detection.fields["calibration.color_rms"] == 0.314855\n    assert summary.fields["color.g-r.diff"] == 0.744712\n',
    '    assert detection.fields["calibration.color_rms"] == 0.314855\n    lightcurve = _records(portfolio, "lightcurve@fink")[0]\n    assert lightcurve.fields["color_points.color.g-r.diff"] == 0.744712\n',
)
replace_exact(
    fink_ztf,
    '    assert "g.feature_vector" in lightcurve.fields and "r.feature_vector" in lightcurve.fields\n',
    '    assert "feature_vector.g.value" in lightcurve.fields\n    assert "feature_vector.r.value" in lightcurve.fields\n',
)
replace_exact(
    fink_ztf,
    '            assert record.fields[f"photometry.{band}.limit.upper_limit"] is True\n',
    '            assert record.fields[f"photometry.{band}.upper_limit"] is True\n',
)
replace_exact(
    fink_ztf,
    '            assert record.fields[f"photometry.{band}.limit.upper_limit"] is False\n',
    '            assert record.fields[f"photometry.{band}.upper_limit"] is False\n',
)
old_fast = '''def test_fast_transient_fields_use_lightcurve_semantics():
    no_rate = [{"i:objectId": "ZTF-synthetic", "i:fid": 1, "d:lower_rate": None, "d:upper_rate": None,
                "d:delta_time": None, "d:from_upper": False}]
    records = _records(_build("anomaly", no_rate), "lightcurve@fink")
    assert not records or "g.from_upper_limit" not in records[0].fields

    upper = [{"i:objectId": "ZTF-synthetic", "i:fid": 2, "d:lower_rate": -0.2, "d:upper_rate": 0.4,
              "d:delta_time": 0.5, "d:from_upper": True}]
    record = _records(_build("anomaly", upper), "lightcurve@fink")[0]
    assert record.fields["r.rate_lower_percentile"] == -0.2
    assert record.fields["r.rate_upper_percentile"] == 0.4
    assert record.fields["r.delta_time_rate"] == 0.5
    assert record.fields["r.from_upper_limit"] is True

    derived = _records(_build("anomaly", [{"i:objectId": "ZTF-synthetic",
        "i:fid": 1, "d:nalerthist": 17, "d:mag_rate": 0.25,
        "d:sigma_rate": 0.05,
    }]), "lightcurve@fink")[0]
    assert derived.semantic_type == "lightcurve@fink"
    assert derived.fields["detection_count"] == 17
    assert derived.fields["g.magnitude_rate"] == 0.25
    assert derived.fields["g.magnitude_rate_error"] == 0.05
'''
new_fast = '''def test_fast_transient_fields_are_explicit_structural_debt_until_rate_point_collection():
    document = yaml.safe_load(MAPPINGS.read_text(encoding="utf-8"))
    mapped = {reference for refs in document["mappings"].values() for reference in refs}
    debt = {
        next(iter(entry))
        for entry in yaml.safe_load(DEBT.read_text(encoding="utf-8"))["unmapped"]
    }
    expected = {
        f"{payload}#{field}"
        for payload in ("objects", "sso", "latests", "anomaly")
        for field in ("d:mag_rate", "d:sigma_rate", "d:lower_rate", "d:upper_rate")
    }
    expected |= {
        f"{payload}#{field}"
        for payload in ("sso", "latests", "anomaly")
        for field in ("d:delta_time", "d:from_upper")
    }
    assert expected <= debt
    assert mapped.isdisjoint(expected)
'''
replace_exact(fink_ztf, old_fast, new_fast)

fink_lsst = ROOT / "tests/test_fink_lsst_authoritative_payloads.py"
replace_exact(
    fink_lsst,
    '    assert not any(path.startswith("lightcurve@lsst:fink") for path in mappings)\n',
    '    assert "lightcurve@lsst:fink.points.photometry.{filter}.psf.flux" in mappings\n    assert "lightcurve@lsst:fink.forced_photometry_points.forced_photometry.{filter}.psf.flux" in mappings\n',
)
old_fp = '''def test_fp_endpoint_emits_twenty_detection_records(tmp_path):
    paths = [path for path, refs in registry()["mappings"].items() if any(ref.startswith("fp#") for ref in refs)]
    portfolio = _build_filtered(tmp_path, "fp", fixture("fp"), paths)
    assert len(portfolio.records) == 20
    assert {record.semantic_type for record in portfolio.records} == {"detection@lsst:fink"}
    row, fields = fixture("fp")[0], dict(portfolio.records[0].fields); band = row["r:band"]
    expected = {"identity.object_id": row["r:diaObjectId"], "identity.source_id": row["r:diaForcedSourceId"], "identity.visit_id": row["r:visit"], "identity.detector_id": row["r:detector"], "time.mjd": row["r:midpointMjdTai"], "position.ra": row["r:ra"], "position.dec": row["r:dec"], f"forced_photometry.{band}.psf.flux": row["r:psfFlux"], f"forced_photometry.{band}.psf.flux.error": row["r:psfFluxErr"]}
    assert {key: fields[key] for key in expected} == expected
'''
new_fp = '''def test_fp_endpoint_preserves_twenty_detection_records_while_exposing_lightcurve_semantics(tmp_path):
    paths = [path for path, refs in registry()["mappings"].items() if any(ref.startswith("fp#") for ref in refs)]
    portfolio = _build_filtered(tmp_path, "fp", fixture("fp"), paths)
    detections = [record for record in portfolio.records if record.semantic_type == "detection@lsst:fink"]
    assert len(detections) == 20
    assert any(record.semantic_type == "lightcurve@lsst:fink" for record in portfolio.records)
    row, fields = fixture("fp")[0], dict(detections[0].fields); band = row["r:band"]
    expected = {"identity.object_id": row["r:diaObjectId"], "identity.source_id": row["r:diaForcedSourceId"], "identity.visit_id": row["r:visit"], "identity.detector_id": row["r:detector"], "time.mjd": row["r:midpointMjdTai"], "position.ra": row["r:ra"], "position.dec": row["r:dec"], f"forced_photometry.{band}.psf.flux": row["r:psfFlux"], f"forced_photometry.{band}.psf.flux.error": row["r:psfFluxErr"]}
    assert {key: fields[key] for key in expected} == expected
'''
replace_exact(fink_lsst, old_fp, new_fp)

alerce_lsst = ROOT / "tests/test_alerce_lsst_authoritative_payloads.py"
replace_exact(
    alerce_lsst,
    '''def test_lightcurve_delegates_all_three_branches_without_edges():
    p=build("query_lightcurve",fixture("query_lightcurve"))
    assert len(p.records)==26 and {r.internal_source.payload_key for r in p.records}=={"query_lightcurve.detections","query_lightcurve.forced_photometry"}
    assert p.edges==()
''',
    '''def test_lightcurve_delegates_all_three_branches_without_edges():
    p=build("query_lightcurve",fixture("query_lightcurve"))
    detections=[r for r in p.records if r.semantic_type=="detection@lsst:alerce"]
    lightcurves=[r for r in p.records if r.semantic_type=="lightcurve@lsst:alerce"]
    assert len(detections)==26
    assert lightcurves
    assert {r.internal_source.payload_key for r in detections}=={"query_lightcurve.detections","query_lightcurve.forced_photometry"}
    assert {r.internal_source.payload_key for r in lightcurves}=={"query_lightcurve.detections","query_lightcurve.forced_photometry"}
    assert p.edges==()
''',
)

lasair_ztf = ROOT / "tests/test_lasair_ztf_authoritative_payloads.py"
replace_exact(
    lasair_ztf,
    '    assert fields["photometry.r.limit.upper_limit"] is True\n',
    '    assert "photometry.r.upper_limit" not in fields\n',
)
replace_exact(
    lasair_ztf,
    '    assert "photometry.g.limit.upper_limit" not in fields\n',
    '    assert "photometry.g.upper_limit" not in fields\n',
)

antares_ztf = ROOT / "tests/test_antares_ztf_authoritative_payloads.py"
replace_exact(
    antares_ztf,
    "    assert sum(f.get('photometry.g.limit.upper_limit') is False or f.get('photometry.r.limit.upper_limit') is False for f in fields)==70\n    assert sum(f.get('photometry.g.limit.upper_limit') is True or f.get('photometry.r.limit.upper_limit') is True for f in fields)==246\n",
    "    assert sum(f.get('photometry.g.upper_limit') is False or f.get('photometry.r.upper_limit') is False for f in fields)==70\n    assert sum(f.get('photometry.g.upper_limit') is True or f.get('photometry.r.upper_limit') is True for f in fields)==246\n",
)

print("Updated mapping debt and authoritative mapping contracts.")
