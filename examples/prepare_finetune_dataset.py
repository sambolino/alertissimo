"""Build a validated English NLP -> DSL fine-tuning set offline.

The generator is deliberately independent of Ollama/OpenAI.  DSL candidates are
constructed from registered broker/survey/product combinations, then accepted only
when the grammar, semantic validator, capability graph, and lowering pipeline all
agree that the result is executable.  The emitted JSONL contains no AST or registry
metadata: only a user request and its canonical DSL answer.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import random
import re
from typing import Callable

from alertissimo.api import validate_dsl
from alertissimo.data_layer.runtime.capability_graph import CapabilityGraph, build_capability_graph


HERE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = HERE.parent / "dataset" / "nlp_finetune_train.jsonl"


@dataclass(frozen=True)
class Variant:
    """One DSL family with a natural-language renderer."""

    build_dsl: Callable[[str, tuple[float, float, str]], str]
    request: Callable[[str, tuple[float, float, str]], str]
    origin: str
    broker: str
    products: tuple[str, ...]
    ids: tuple[str, ...]
    needs_coordinates: bool = False


ZTFS = (
    "ZTF18acurdih",
    "ZTF18abbuksn",
    "ZTF19aabcedf",
    "ZTF20aafqubg",
    "ZTF20acpwljl",
    "ZTF21abfmbix",
    "ZTF22abcdefg",
)
LSSTS = (
    "313936986529333309",
    "170587117485817955",
    "313761042336317573",
    "170587117485817955",
)
COORDINATES = (
    (124.87996, -6.02050, "5arcsec"),
    (210.25, -12.5, "2arcsec"),
    (15.75, 22.1, "30arcsec"),
    (305.58223, -18.79092, "1arcsec"),
    (150.12452, 0.87758, "300arcsec"),
)


def _object_lightcurve(origin: str, broker: str, product: str = "lightcurve") -> Variant:
    def dsl(identifier: str, _coord: tuple[float, float, str]) -> str:
        return f"object {identifier} from {origin} via {broker}\nwith {product} via {broker}"

    def request(identifier: str, _coord: tuple[float, float, str]) -> str:
        article = "the " if product == "lightcurve" else "its "
        noun = "light curve" if product == "lightcurve" else product
        return f"Retrieve {article}{noun} for {origin.upper()} object {identifier} through {broker.title()}."

    ids = LSSTS if origin == "lsst" else ZTFS
    return Variant(dsl, request, origin, broker, (product,), ids)


def _object_crossmatch_lightcurve() -> Variant:
    def dsl(identifier: str, _coord: tuple[float, float, str]) -> str:
        return (
            f"object {identifier} from ztf via antares\n"
            "with crossmatch from gaia via antares\n"
            "with lightcurve via antares"
        )

    def request(identifier: str, _coord: tuple[float, float, str]) -> str:
        return f"Find ZTF object {identifier} through Antares and return its Gaia crossmatch and light curve."

    return Variant(dsl, request, "ztf", "antares", ("crossmatch", "lightcurve"), ZTFS)


def _cone_latest(origin: str, broker: str, latest: int) -> Variant:
    def dsl(_identifier: str, coord: tuple[float, float, str]) -> str:
        ra, dec, radius = coord
        return f"objects from {origin} via {broker}\ninside ({ra:g}, {dec:g}, {radius})\nlatest {latest}"

    def request(_identifier: str, coord: tuple[float, float, str]) -> str:
        ra, dec, radius = coord
        return f"Find the latest {latest} {origin.upper()} objects through {broker.title()} within {radius} of RA {ra:g} degrees and Dec {dec:g} degrees."

    ids = LSSTS if origin == "lsst" else ZTFS
    return Variant(dsl, request, origin, broker, (), ids, needs_coordinates=True)


def _cone_lightcurves() -> Variant:
    def dsl(_identifier: str, coord: tuple[float, float, str]) -> str:
        ra, dec, radius = coord
        return (
            f"objects from ztf via fink\ninside ({ra:g}, {dec:g}, {radius})\n"
            "with lightcurve via fink\nwith lightcurve via lasair"
        )

    def request(_identifier: str, coord: tuple[float, float, str]) -> str:
        ra, dec, radius = coord
        return f"Search Fink for ZTF objects within {radius} of RA {ra:g} degrees and Dec {dec:g} degrees, then return their light curves from Fink and Lasair."

    return Variant(dsl, request, "ztf", "fink", ("lightcurve",), ZTFS, needs_coordinates=True)


def _within_latest() -> Variant:
    def dsl(_identifier: str, _coord: tuple[float, float, str]) -> str:
        return "objects from ztf via fink\nwithin 7d\nlatest 10"

    def request(_identifier: str, _coord: tuple[float, float, str]) -> str:
        return "Find the latest 10 ZTF objects reported through Fink during the last 7 days."

    return Variant(dsl, request, "ztf", "fink", (), ZTFS)


def _multisurvey_cone() -> Variant:
    def dsl(_identifier: str, coord: tuple[float, float, str]) -> str:
        ra, dec, radius = coord
        return f"objects from lsst, ztf via alerce\ninside ({ra:g}, {dec:g}, {radius})\nlatest 5"

    def request(_identifier: str, coord: tuple[float, float, str]) -> str:
        ra, dec, radius = coord
        return f"Through ALeRCE, find the latest 5 objects from LSST or ZTF within {radius} of RA {ra:g} degrees and Dec {dec:g} degrees."

    return Variant(dsl, request, "ztf", "alerce", (), ZTFS, needs_coordinates=True)


def _variants() -> tuple[Variant, ...]:
    return (
        _object_lightcurve("ztf", "antares"),
        _object_lightcurve("ztf", "alerce"),
        _object_lightcurve("ztf", "fink"),
        _object_lightcurve("ztf", "lasair"),
        _object_lightcurve("lsst", "fink"),
        _object_lightcurve("lsst", "alerce"),
        _object_lightcurve("lsst", "lasair"),
        _object_lightcurve("ztf", "fink", "classification"),
        _object_crossmatch_lightcurve(),
        _cone_latest("ztf", "alerce", 3),
        _cone_latest("lsst", "lasair", 5),
        _multisurvey_cone(),
        _cone_lightcurves(),
        _within_latest(),
    )


def _record_exists(graph: CapabilityGraph, variant: Variant) -> bool:
    return all(
        graph.query_records(
            broker=variant.broker,
            origin=variant.origin,
            semantic_record_noun=product,
        )
        for product in variant.products
    )


def _formulations(dsl: str, canonical: str) -> tuple[str, ...]:
    """Return several realistic English phrasings for one canonical DSL."""
    first, *clauses = dsl.splitlines()
    if first.startswith("object "):
        _, identifier, _, origin, _, broker = first.split()
        if any("crossmatch" in clause for clause in clauses):
            return (
                f"Find {origin.upper()} object {identifier} through {broker.title()} and return its Gaia match and light curve.",
                f"Look up {identifier} from {origin.upper()} using {broker.title()}, including the Gaia crossmatch and light curve.",
                f"For {origin.upper()} source {identifier}, get the Gaia crossmatch and the light curve via {broker.title()}.",
                f"Use {broker.title()} to retrieve {origin.upper()} object {identifier} with its Gaia counterpart and light curve.",
                f"Return the Gaia counterpart and light curve for {origin.upper()} object {identifier}, using {broker.title()}.",
                f"For {origin.upper()} object {identifier}, obtain the Gaia crossmatch plus light curve with {broker.title()}.",
                f"I need the Gaia match and light curve for {origin.upper()} source {identifier} from {broker.title()}.",
                f"Fetch {origin.upper()} object {identifier} via {broker.title()} and include Gaia matching and light-curve data.",
                f"Can {broker.title()} return the Gaia counterpart and light curve associated with {origin.upper()} object {identifier}?",
                f"Retrieve both Gaia matching information and the light curve for {identifier} through {broker.title()}.",
            )
        if any("classification" in clause for clause in clauses):
            return (
                f"Find {origin.upper()} object {identifier} in {broker.title()} and return its classification.",
                f"Retrieve the classification of {origin.upper()} source {identifier} through {broker.title()}.",
                f"Using {broker.title()}, look up {identifier} from {origin.upper()} and get its class.",
                f"Return the {broker.title()} classification for {origin.upper()} object {identifier}.",
                f"What classification does {broker.title()} provide for {origin.upper()} object {identifier}?",
                f"Get the class assigned by {broker.title()} to {origin.upper()} object {identifier}.",
                f"For {identifier} from {origin.upper()}, retrieve the classification supplied by {broker.title()}.",
                f"Look up the {broker.title()} class for {origin.upper()} source {identifier}.",
                f"Please return {origin.upper()} object {identifier}'s classification from {broker.title()}.",
                f"Which classification does {broker.title()} report for {identifier}?",
            )
        return (
            f"Get the light curve for {origin.upper()} object {identifier} from {broker.title()}.",
            f"Retrieve {origin.upper()} source {identifier}'s light curve through {broker.title()}.",
            f"Using {broker.title()}, return the light curve of {origin.upper()} object {identifier}.",
            f"Look up {identifier} in {broker.title()} and provide its {origin.upper()} light curve.",
            f"Please fetch {origin.upper()} object {identifier}'s light curve from {broker.title()}.",
            f"From {broker.title()}, obtain the time-series light curve of {origin.upper()} source {identifier}.",
            f"I need the {origin.upper()} light curve associated with {identifier}; use {broker.title()}.",
            f"Can you return the light curve for {origin.upper()} object {identifier} via {broker.title()}?",
            f"Query {broker.title()} for the light curve belonging to {origin.upper()} object {identifier}.",
            f"Provide all available light-curve data for {identifier} from {broker.title()}.",
        )

    if "within 7d" in dsl:
        return (
            "Find the latest 10 ZTF objects reported by Fink in the last 7 days.",
            "Return ten newest ZTF objects from Fink with observations during the past week.",
            "Using Fink, list the 10 most recent ZTF objects seen within the previous 7 days.",
            "Show the latest ten Fink ZTF objects from the last seven days.",
            "List ten newest ZTF objects from Fink with data from the past week.",
            "Give me the ten most recent ZTF sources in Fink seen over the past week.",
            "Query Fink for ten latest ZTF objects with observations in the previous seven days.",
            "Return the newest ten ZTF objects from Fink, limited to the last seven days.",
            "Which ten ZTF objects are most recent in Fink during the past week?",
            "Show ten recent Fink ZTF objects whose data falls within seven days.",
        )
    match = re.search(r"objects from (.+?) via (\w+)\ninside \(([^,]+), ([^,]+), ([^)]+)\)", dsl)
    if match:
        origins, broker, ra, dec, radius = match.groups()
        origin_words = " and ".join(item.upper() for item in origins.split(", "))
        suffix = "latest 5" in dsl
        number = 5 if suffix else None
        latest = f"the latest {number} " if number else ""
        products = " Return their light curves from Fink and Lasair." if "with lightcurve" in dsl else ""
        return (
            f"Find {latest}{origin_words} objects through {broker.title()} within {radius} of RA {ra} degrees and Dec {dec} degrees.{products}",
            f"Search {broker.title()} for {latest}{origin_words} sources around ({ra}, {dec}) with a {radius} radius.{products}",
            f"Return {latest}{origin_words} objects from {broker.title()} inside a {radius} cone centered at RA {ra}, Dec {dec}.{products}",
            f"Using {broker.title()}, list {latest}{origin_words} objects no farther than {radius} from RA {ra} degrees and Dec {dec} degrees.{products}",
            f"Give me {latest}{origin_words} sources from {broker.title()} near ({ra}, {dec}), within {radius}.{products}",
            f"Query {broker.title()} for {latest}{origin_words} objects centered on RA {ra}, Dec {dec}, with a {radius} search radius.{products}",
            f"Find {latest}{origin_words} sources in a {radius} cone at ({ra}, {dec}) using {broker.title()}.{products}",
            f"Return {latest}{origin_words} objects near RA {ra} degrees and Dec {dec} degrees, no more than {radius} away, via {broker.title()}.{products}",
            f"Use {broker.title()} to search a {radius} region around ({ra}, {dec}) for {latest}{origin_words} objects.{products}",
            f"I need {latest}{origin_words} objects from {broker.title()} within {radius} of the sky position RA {ra}, Dec {dec}.{products}",
        )
    return (canonical,)


def _rows(graph: CapabilityGraph, seed: int) -> list[dict[str, object]]:
    rng = random.Random(seed)
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    coordinates = list(COORDINATES)
    variants = list(_variants())
    rng.shuffle(variants)
    for variant in variants:
        if not _record_exists(graph, variant):
            continue
        identifiers = list(variant.ids)
        rng.shuffle(identifiers)
        rng.shuffle(coordinates)
        for identifier in identifiers:
            for coord in coordinates if variant.needs_coordinates else [COORDINATES[0]]:
                dsl = variant.build_dsl(identifier, coord)
                validation = validate_dsl(dsl, graph=graph, name="fine-tuning candidate")
                if not validation.is_runnable:
                    continue
                canonical = variant.request(identifier, coord)
                for request in _formulations(dsl, canonical):
                    key = (request, dsl)
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append(
                        {
                            "messages": [
                                {"role": "user", "content": request},
                                {"role": "assistant", "content": dsl},
                            ]
                        }
                    )
    groups: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        dsl = str(row["messages"][1]["content"])
        groups.setdefault(dsl, []).append(row)
    group_list = list(groups.values())
    rng.shuffle(group_list)
    return [row for group in group_list for row in group]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--count", type=int, default=0, help="optional row limit; must preserve complete 10-row DSL groups")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.count < 0 or (args.count and args.count % 10):
        parser.error("--count must be zero (all rows) or a positive multiple of 10")

    graph = build_capability_graph()
    rows = _rows(graph, args.seed)
    if args.count and len(rows) < args.count:
        raise SystemExit(f"only {len(rows)} executable unique rows available; requested {args.count}")
    selected = rows[: args.count] if args.count else rows
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in selected),
        encoding="utf-8",
    )
    print(f"wrote {len(selected)} rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
