from __future__ import annotations

from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[2]
ONTOLOGY = ROOT / "alertissimo/data_layer/semantic_model/ontology.yaml"
FINK = ROOT / "alertissimo/data_layer/providers/fink/lsst/mappings.yaml"
FINK_DEBT = ROOT / "alertissimo/data_layer/providers/fink/lsst/unmapped_fields.yaml"
ALERCE = ROOT / "alertissimo/data_layer/providers/alerce/lsst/mappings.yaml"
ANTARES = ROOT / "alertissimo/data_layer/providers/antares/lsst/mappings.yaml"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_ontology() -> None:
    text = ONTOLOGY.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '  [distance_to_edge]:\n    description: "Distance to nearest image edge"\n    unit: pixels\n  level: L1, L6\n',
        '  [distance_to_edge]:\n    description: "Distance to nearest image edge"\n    unit: pixels\n  <galactic>:\n    description: "Galactic coordinates of the represented position"\n    [longitude]:\n      unit: deg\n    [latitude]:\n      unit: deg\n  level: L1, L6\n',
        "position.galactic",
    )

    text = replace_once(
        text,
        '  level: L7\n  [snapshot_datetime]:\n    description: "Date/time of a survey, stream, statistics, or selection snapshot"\n    unit: datetime\n<identity>:\n',
        '  level: L7\n  [snapshot_datetime]:\n    description: "Date/time of a survey, stream, statistics, or selection snapshot"\n    unit: datetime\n  [night]:\n    description: "Survey or observing-night identifier associated with the snapshot"\n<identity>:\n',
        "time.night",
    )

    text = replace_once(
        text,
        '<solar_system>:\n  level: L2\n  description: "Solar System object - specific information"\n',
        '<solar_system>:\n  level: L2\n  description: "Solar System object - specific information"\n  $ref: <identity>(L0)\n  [designation]:\n    description: "Solar System object designation"\n  [name]:\n    description: "Solar System object name"\n  <match>:\n    description: "Association or ranking metadata for a Solar System counterpart"\n    [rank]:\n      description: "Rank of the associated Solar System counterpart"\n      type: integer\n  <ecliptic>:\n    description: "Ecliptic coordinates associated with the Solar System object"\n    [longitude]:\n      unit: deg\n    [latitude]:\n      unit: deg\n  [phase_angle]:\n    description: "Solar phase angle"\n    unit: deg\n  [elongation]:\n    description: "Solar elongation"\n    unit: deg\n  <ephemeris>:\n    description: "Predicted ephemeris quantities associated with the Solar System object"\n    [ra]:\n      unit: deg\n    [dec]:\n      unit: deg\n    [vmag]:\n      unit: mag\n    <offset>:\n      [total]:\n      [ra]:\n      [dec]:\n      [along_track]:\n      [cross_track]:\n    <rate>:\n      [total]:\n      [ra]:\n      [dec]:\n  <heliocentric>:\n    description: "Heliocentric state-vector quantities"\n    [range]:\n    [range_rate]:\n    <position>:\n      [x]:\n      [y]:\n      [z]:\n    <velocity>:\n      [x]:\n      [y]:\n      [z]:\n      [total]:\n  <topocentric>:\n    description: "Topocentric state-vector quantities"\n    [range]:\n    [range_rate]:\n    <position>:\n      [x]:\n      [y]:\n      [z]:\n    <velocity>:\n      [x]:\n      [y]:\n      [z]:\n      [total]:\n',
        "solar-system reusable structures",
    )

    text = replace_once(
        text,
        '  $ref: <forced_photometry>(L0)\n  $ref: <color>(L0)\n  $ref: <flags>(L0)\n',
        '  $ref: <forced_photometry>(L0)\n  $ref: <color>(L0)\n  $ref: <flags>(L0)\n  $ref: <provenance>\n',
        "summary provenance",
    )

    text = replace_once(
        text,
        '  $ref: <classification>\n  $ref: <provenance>\n  $ref: <astrometric_solution>\n',
        '  $ref: <classification>\n  $ref: <quality>(L6)\n  $ref: <provenance>\n  $ref: <astrometric_solution>\n',
        "crossmatch quality",
    )

    text = replace_once(
        text,
        '  [filter_counts]:\n    description: "Alert or record counts per filter"\n    type: object\n  [exposure_count]:\n',
        '  [filter_counts]:\n    description: "Alert or record counts per filter"\n    type: object\n    [{filter}]:\n      description: "Alert or record count for this filter"\n      type: integer\n  [alert_count]:\n    description: "Number of alerts represented by the survey snapshot"\n    type: integer\n  [object_count]:\n    description: "Number of objects represented by the survey snapshot"\n    type: integer\n  [visit_count]:\n    description: "Number of visits represented by the survey snapshot"\n    type: integer\n  <flag_counts>:\n    description: "Counts grouped by boolean/status flag"\n    [{flag}]:\n      type: integer\n    <pixel_flags>:\n      [{flag}]:\n        type: integer\n  [exposure_count]:\n',
        "survey counts",
    )

    ONTOLOGY.write_text(text, encoding="utf-8")


def remove_mapping_blocks(text: str, semantic_paths: set[str]) -> str:
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    removed: set[str] = set()
    key_re = re.compile(r"^  ([^\s-][^:]*@[^:]+:[^:]+\..*):\s*$")
    while i < len(lines):
        match = key_re.match(lines[i].rstrip("\n"))
        if match and match.group(1) in semantic_paths:
            removed.add(match.group(1))
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if key_re.match(nxt.rstrip("\n")) or re.match(r"^[A-Za-z_][^:]*:\s*$", nxt.rstrip("\n")):
                    break
                i += 1
            continue
        out.append(lines[i])
        i += 1
    missing = semantic_paths - removed
    if missing:
        raise RuntimeError(f"science-flux mapping block(s) not found: {sorted(missing)}")
    return "".join(out)


def patch_provider_mappings() -> list[str]:
    # Reusable Rubin Solar-System identity: the native ssObjectId is the object
    # identity itself, not an MPC-nearest-match identity.
    for path in (ALERCE, ANTARES, FINK):
        text = path.read_text(encoding="utf-8")
        text = text.replace(
            "solar_system.object.identity.object_id",
            "solar_system.identity.object_id",
        )
        path.write_text(text, encoding="utf-8")

    text = FINK.read_text(encoding="utf-8")
    replacements = {
        "summary@lsst:fink.crossmatch.best.class":
            "classification@fink.assessment.crossmatch.class",
        "detection@lsst:fink.solar_system.object.designation":
            "detection@lsst:fink.solar_system.designation",
        "detection@lsst:fink.solar_system.object.name":
            "detection@lsst:fink.solar_system.name",
        "crossmatch@gaia:fink.parallax.value":
            "crossmatch@gaia:fink.astrometric_solution.parallax",
        "crossmatch@gaia:fink.parallax.error":
            "crossmatch@gaia:fink.astrometric_solution.parallax_error",
        "crossmatch@gaia:fink.classification.variability_flag":
            "crossmatch@gaia:fink.classification.assessment.variability.flag",
        "crossmatch@legacydr8:fink.classification.star_probability":
            "crossmatch@legacydr8:fink.classification.assessment.star.probability",
        "portfolio.survey@lsst:fink.":
            "survey@lsst:fink.",
    }
    for old, new in replacements.items():
        if old not in text:
            raise RuntimeError(f"expected Fink mapping token not found: {old}")
        text = text.replace(old, new)

    science_paths = {
        f"summary@lsst:fink.forced_photometry.{band}.science.flux.{suffix}"
        for band in "ugrizy"
        for suffix in ("mean", "mean_error")
    }
    text = remove_mapping_blocks(text, science_paths)
    FINK.write_text(text, encoding="utf-8")

    debt_refs = []
    for band in "ugrizy":
        debt_refs.extend([
            f"objects#r:{band}_scienceFluxMean",
            f"conesearch#r:{band}_scienceFluxMean",
            f"objects#r:{band}_scienceFluxMeanErr",
            f"conesearch#r:{band}_scienceFluxMeanErr",
        ])
    return debt_refs


def patch_debt(debt_refs: list[str]) -> None:
    document = yaml.safe_load(FINK_DEBT.read_text(encoding="utf-8"))
    entries = document.setdefault("unmapped", [])
    existing = {next(iter(entry)) for entry in entries}
    for ref in debt_refs:
        if ref in existing:
            continue
        entries.append({
            ref: {
                "reason": "structural_measurement_semantics",
                "note": (
                    "Rubin DiaObject scienceFlux aggregate is distinct from the existing "
                    "forced-photometry aggregate and cannot be placed under a fabricated "
                    "science subcontainer. Keep explicit debt until the image-plane/aggregate "
                    "measurement structure is modeled without semantic collision."
                ),
            }
        })
    FINK_DEBT.write_text(
        "---\n" + yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def patch_tests() -> None:
    for path in (ROOT / "tests").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        new = text.replace(
            "solar_system.object.identity.object_id",
            "solar_system.identity.object_id",
        )
        new = new.replace(
            "portfolio.survey@lsst:fink.",
            "survey@lsst:fink.",
        )
        if new != text:
            path.write_text(new, encoding="utf-8")


if __name__ == "__main__":
    patch_ontology()
    debt = patch_provider_mappings()
    patch_debt(debt)
    patch_tests()
