from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

ROOT = Path("alertissimo/data_layer/providers")
FILES = {
    "fink_ztf": ROOT / "fink/ztf/mappings.yaml",
    "fink_lsst": ROOT / "fink/lsst/mappings.yaml",
    "alerce_ztf": ROOT / "alerce/ztf/mappings.yaml",
    "alerce_lsst": ROOT / "alerce/lsst/mappings.yaml",
    "lasair_ztf": ROOT / "lasair/ztf/mappings.yaml",
    "antares_ztf": ROOT / "antares/ztf/mappings.yaml",
}

ENTRY = re.compile(r"(?m)^  ([^\n]+):\n")
CHILD = re.compile(r"(?m)^    ([^\n]+?):(?:\s+([&*][^\n]+))?\n")


@dataclass
class Entry:
    key: str
    text: str


class Section:
    def __init__(self, body: str):
        matches = list(ENTRY.finditer(body))
        if not matches:
            self.preamble = body
            self.entries: list[Entry] = []
            return
        self.preamble = body[: matches[0].start()]
        self.entries = []
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
            self.entries.append(Entry(match.group(1), body[match.start() : end]))

    def find(self, key: str) -> Entry | None:
        return next((entry for entry in self.entries if entry.key == key), None)

    def require(self, key: str) -> Entry:
        entry = self.find(key)
        if entry is None:
            raise RuntimeError(f"missing semantic entry: {key}")
        return entry

    def rename(self, old: str, new: str) -> None:
        entry = self.require(old)
        if self.find(new) is not None:
            raise RuntimeError(f"destination already exists: {new}")
        entry.text = entry.text.replace(f"  {old}:\n", f"  {new}:\n", 1)
        entry.key = new

    def remove(self, key: str) -> None:
        self.entries.remove(self.require(key))

    def add(self, key: str, lines: list[str]) -> None:
        if not lines:
            return
        if self.find(key) is not None:
            raise RuntimeError(f"unexpected pre-existing destination entry: {key}")
        text = f"  {key}:\n" + "".join(lines)
        if not text.endswith("\n"):
            text += "\n"
        self.entries.append(Entry(key, text))

    def render(self) -> str:
        return self.preamble + "".join(entry.text for entry in self.entries)


class Document:
    def __init__(self, path: Path):
        self.path = path
        text = path.read_text()
        mapping_marker = "mappings:\n"
        transform_marker = "transforms:\n"
        m = text.index(mapping_marker)
        t = text.index(transform_marker, m + len(mapping_marker))
        self.before = text[: m + len(mapping_marker)]
        self.mappings = Section(text[m + len(mapping_marker) : t])
        self.transform_header = transform_marker
        self.transforms = Section(text[t + len(transform_marker) :])

    def rename(self, old: str, new: str) -> None:
        self.mappings.rename(old, new)
        if self.transforms.find(old) is not None:
            self.transforms.rename(old, new)

    def remove(self, key: str) -> None:
        self.mappings.remove(key)
        if self.transforms.find(key) is not None:
            self.transforms.remove(key)

    def save(self) -> None:
        self.path.write_text(
            self.before
            + self.mappings.render()
            + self.transform_header
            + self.transforms.render()
        )


def mapping_refs(block: str) -> list[str]:
    return [line[4:].strip() for line in block.splitlines() if line.startswith("  - ")]


def transform_children(block: str) -> dict[str, str]:
    matches = list(CHILD.finditer(block))
    children: dict[str, str] = {}
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(block)
        raw = match.group(1)
        marker = match.group(2)
        child = block[match.start() : end]
        if marker and marker.startswith("&"):
            child = f"    {raw}: *{marker[1:]}\n"
        children[raw] = child
    return children


def copy_refs(doc: Document, src: str, dst: str, payloads: set[str]) -> None:
    source = doc.mappings.require(src)
    selected = [
        raw for raw in mapping_refs(source.text) if raw.split("#", 1)[0] in payloads
    ]
    doc.mappings.add(dst, [f"  - {raw}\n" for raw in selected])
    source_transform = doc.transforms.find(src)
    if source_transform is None:
        return
    children = transform_children(source_transform.text)
    chosen = [children[raw] for raw in selected if raw in children]
    if chosen:
        doc.transforms.add(dst, chosen)


def copy_point_sources(
    doc: Document,
    src_record: str,
    dst_record: str,
    payloads: set[str],
    roots: set[str],
) -> None:
    snapshot = list(doc.mappings.entries)
    prefix = src_record + "."
    for entry in snapshot:
        if not entry.key.startswith(prefix):
            continue
        suffix = entry.key[len(prefix) :]
        if suffix.split(".", 1)[0] not in roots:
            continue
        selected = [
            raw for raw in mapping_refs(entry.text) if raw.split("#", 1)[0] in payloads
        ]
        if not selected:
            continue
        dst = dst_record + "." + suffix
        doc.mappings.add(dst, [f"  - {raw}\n" for raw in selected])
        source_transform = doc.transforms.find(entry.key)
        if source_transform is None:
            continue
        children = transform_children(source_transform.text)
        chosen = [children[raw] for raw in selected if raw in children]
        if chosen:
            doc.transforms.add(dst, chosen)


def strip_transform_children(path: Path, raw_refs: set[str]) -> None:
    """Remove dangling transform children for deliberately unmapped raw fields."""
    text = path.read_text()
    for raw in raw_refs:
        pattern = re.compile(
            rf"(?m)^    {re.escape(raw)}:[^\n]*\n(?:^ {{6,}}.*\n|^\s*$\n?)*"
        )
        text = pattern.sub("", text)
    path.write_text(text)


def assert_absent(path: Path, tokens: tuple[str, ...]) -> None:
    text = path.read_text()
    for token in tokens:
        if token in text:
            raise RuntimeError(f"unexpected deferred/obsolete token remains in {path}: {token}")


# Fink / ZTF -----------------------------------------------------------------
doc = Document(FILES["fink_ztf"])
doc.rename(
    "detection@ztf:fink.photometry.{filter}.limit.upper_limit",
    "detection@ztf:fink.photometry.{filter}.upper_limit",
)
doc.rename("lightcurve@fink.g.feature_vector", "lightcurve@fink.feature_vector.g.value")
doc.rename("lightcurve@fink.r.feature_vector", "lightcurve@fink.feature_vector.r.value")
doc.rename(
    "summary@ztf:fink.photometry.{filter}",
    "lightcurve@fink.magnitude_rate_points.photometry.{filter}",
)
doc.rename(
    "summary@ztf:fink.photometry.{filter}.mag.rate",
    "lightcurve@fink.magnitude_rate_points.photometry.{filter}.mag.rate",
)
doc.rename(
    "summary@ztf:fink.photometry.{filter}.mag.rate_error",
    "lightcurve@fink.magnitude_rate_points.photometry.{filter}.mag.rate_error",
)
copy_refs(
    doc,
    "detection@ztf:fink.time.mjd",
    "lightcurve@fink.magnitude_rate_points.time.mjd",
    {"objects", "latests"},
)
copy_refs(
    doc,
    "detection@ztf:fink.identity.source_id",
    "lightcurve@fink.magnitude_rate_points.identity.source_id",
    {"objects", "latests"},
)
for tail in ("diff", "error", "rate", "rate_error"):
    doc.rename(
        f"summary@ztf:fink.color.g-r.{tail}",
        f"lightcurve@fink.color_points.color.g-r.{tail}",
    )
copy_refs(
    doc,
    "detection@ztf:fink.time.mjd",
    "lightcurve@fink.color_points.time.mjd",
    {"objects", "latests"},
)
copy_refs(
    doc,
    "detection@ztf:fink.identity.source_id",
    "lightcurve@fink.color_points.identity.source_id",
    {"objects", "latests"},
)
for key in (
    "lightcurve@fink.{filter}.rate_lower_percentile",
    "lightcurve@fink.{filter}.rate_upper_percentile",
    "lightcurve@fink.{filter}.delta_time_rate",
    "lightcurve@fink.{filter}.from_upper_limit",
    "lightcurve@fink.{filter}",
    "lightcurve@fink.{filter}.magnitude_rate",
    "lightcurve@fink.{filter}.magnitude_rate_error",
):
    doc.remove(key)
copy_point_sources(
    doc,
    "detection@ztf:fink",
    "lightcurve@ztf:fink.points",
    {"objects"},
    {"time", "identity", "quality", "provenance", "photometry"},
)
doc.save()

fink_deferred_raw = {
    f"{payload}#{field}"
    for payload in ("objects", "sso", "latests", "anomaly")
    for field in ("d:mag_rate", "d:sigma_rate", "d:lower_rate", "d:upper_rate")
}
fink_deferred_raw |= {
    f"{payload}#{field}"
    for payload in ("sso", "latests", "anomaly")
    for field in ("d:delta_time", "d:from_upper")
}
strip_transform_children(FILES["fink_ztf"], fink_deferred_raw)
assert_absent(
    FILES["fink_ztf"],
    (
        "lightcurve@fink.{filter}.rate_lower_percentile",
        "lightcurve@fink.{filter}.rate_upper_percentile",
        "lightcurve@fink.{filter}.delta_time_rate",
        "lightcurve@fink.{filter}.from_upper_limit",
        "lightcurve@fink.{filter}.magnitude_rate",
        "lightcurve@fink.{filter}.magnitude_rate_error",
        "#d:mag_rate",
        "#d:sigma_rate",
        "#d:lower_rate",
        "#d:upper_rate",
        "#d:delta_time",
        "#d:from_upper",
    ),
)

# Fink / LSST ----------------------------------------------------------------
doc = Document(FILES["fink_lsst"])
copy_point_sources(
    doc,
    "detection@lsst:fink",
    "lightcurve@lsst:fink.points",
    {"sources"},
    {"time", "identity", "quality", "provenance", "photometry"},
)
copy_point_sources(
    doc,
    "detection@lsst:fink",
    "lightcurve@lsst:fink.forced_photometry_points",
    {"fp"},
    {"time", "identity", "quality", "provenance", "forced_photometry"},
)
doc.save()

# ALeRCE / ZTF ---------------------------------------------------------------
doc = Document(FILES["alerce_ztf"])
copy_point_sources(
    doc,
    "detection@ztf:alerce",
    "lightcurve@ztf:alerce.points",
    {"query_lightcurve.detections", "query_lightcurve.non_detections"},
    {"time", "identity", "quality", "provenance", "photometry"},
)
copy_point_sources(
    doc,
    "detection@ztf:alerce",
    "lightcurve@ztf:alerce.forced_photometry_points",
    {"query_forced_photometry"},
    {"time", "identity", "quality", "provenance", "forced_photometry"},
)
doc.save()

# ALeRCE / LSST --------------------------------------------------------------
doc = Document(FILES["alerce_lsst"])
copy_point_sources(
    doc,
    "detection@lsst:alerce",
    "lightcurve@lsst:alerce.points",
    {"query_lightcurve.detections", "query_lightcurve.non_detections"},
    {"time", "identity", "quality", "provenance", "photometry"},
)
copy_point_sources(
    doc,
    "detection@lsst:alerce",
    "lightcurve@lsst:alerce.forced_photometry_points",
    {"query_forced_photometry", "query_lightcurve.forced_photometry"},
    {"time", "identity", "quality", "provenance", "forced_photometry"},
)
doc.save()

# Lasair / ZTF ---------------------------------------------------------------
doc = Document(FILES["lasair_ztf"])
doc.remove("detection@ztf:lasair.photometry.{filter}.limit.upper_limit")
copy_point_sources(
    doc,
    "detection@ztf:lasair",
    "lightcurve@ztf:lasair.points",
    {"lightcurve_candidates"},
    {"time", "identity", "quality", "provenance", "photometry"},
)
doc.save()
lasair_upper_raw = {
    "candidates#diffmaglim",
    "lightcurve_candidates#diffmaglim",
    "objects_candidates#diffmaglim",
}
strip_transform_children(FILES["lasair_ztf"], lasair_upper_raw)
assert_absent(
    FILES["lasair_ztf"],
    ("detection@ztf:lasair.photometry.{filter}.limit.upper_limit",),
)

# ANTARES / ZTF --------------------------------------------------------------
doc = Document(FILES["antares_ztf"])
doc.rename(
    "detection@ztf:antares.photometry.{filter}.limit.upper_limit",
    "detection@ztf:antares.photometry.{filter}.upper_limit",
)
doc.save()

print("Applied targeted time-series mapping migration.")
