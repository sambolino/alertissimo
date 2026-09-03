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


def _filter_quality() -> Variant:
    def dsl(_identifier: str, coord: tuple[float, float, str]) -> str:
        ra, dec, radius = coord
        return (
            f"objects from ztf via fink\ninside ({ra:g}, {dec:g}, {radius})\n"
            "filter detection@ztf:fink.quality.real_bogus >= 0.8"
        )

    def request(_identifier: str, coord: tuple[float, float, str]) -> str:
        ra, dec, radius = coord
        return (
            f"Find ZTF objects from Fink within {radius} of RA {ra:g} and Dec {dec:g} "
            "and keep only detections with real-bogus score at least 0.8."
        )

    return Variant(dsl, request, "ztf", "fink", (), ZTFS, needs_coordinates=True)


def _where_classification() -> Variant:
    def dsl(_identifier: str, _coord: tuple[float, float, str]) -> str:
        return (
            "objects from ztf via alerce\n"
            'where classification@alerce.best.class = "SN" AND '
            "classification@alerce.best.probability >= 0.5"
        )

    def request(_identifier: str, _coord: tuple[float, float, str]) -> str:
        return "Find ALeRCE ZTF objects classified as SN with probability at least 0.5."

    return Variant(dsl, request, "ztf", "alerce", (), ZTFS)


def _match_position() -> Variant:
    def dsl(_identifier: str, coord: tuple[float, float, str]) -> str:
        ra, dec, radius = coord
        return (
            f"objects from lsst, ztf via alerce\ninside ({ra:g}, {dec:g}, {radius})\n"
            "match on position inside 1arcsec"
        )

    def request(_identifier: str, coord: tuple[float, float, str]) -> str:
        ra, dec, radius = coord
        return (
            f"Find LSST and ZTF objects through ALeRCE within {radius} of RA {ra:g}, "
            "Dec {dec:g}, retaining only positional matches within 1 arcsecond."
        ).format(ra=ra, dec=dec)

    return Variant(dsl, request, "ztf", "alerce", (), ZTFS, needs_coordinates=True)


def _order_latest() -> Variant:
    def dsl(_identifier: str, coord: tuple[float, float, str]) -> str:
        ra, dec, radius = coord
        return (
            f"objects from ztf via alerce\ninside ({ra:g}, {dec:g}, {radius})\n"
            "latest 10\norder by summary.time.last_mjd desc"
        )

    def request(_identifier: str, coord: tuple[float, float, str]) -> str:
        ra, dec, radius = coord
        return (
            f"Return the 10 most recent ALeRCE ZTF objects within {radius} of "
            f"RA {ra:g} and Dec {dec:g}, ordered by latest observation first."
        )

    return Variant(dsl, request, "ztf", "alerce", (), ZTFS, needs_coordinates=True)


def _confirm_classification() -> Variant:
    def dsl(_identifier: str, _coord: tuple[float, float, str]) -> str:
        return (
            "objects from ztf via fink\n"
            "where exists classification.best.class\n"
            "confirm by 2 via fink, lasair"
        )

    def request(_identifier: str, _coord: tuple[float, float, str]) -> str:
        return "Find ZTF objects from Fink whose classification is confirmed by both Fink and Lasair."

    return Variant(dsl, request, "ztf", "fink", (), ZTFS)


def _object_product_combo(
    origin: str,
    broker: str,
    requirements: tuple[tuple[str, str], ...],
) -> Variant:
    def dsl(identifier: str, _coord: tuple[float, float, str]) -> str:
        lines = [f"object {identifier} from {origin} via {broker}"]
        lines.extend(f"with {product} via {provider}" for product, provider in requirements)
        return "\n".join(lines)

    def request(identifier: str, _coord: tuple[float, float, str]) -> str:
        products = ", ".join(product.replace("lightcurve", "light curve") for product, _ in requirements)
        return f"Retrieve {products} for {origin.upper()} object {identifier} using {broker.title()}."

    ids = LSSTS if origin == "lsst" else ZTFS
    return Variant(dsl, request, origin, broker, (), ids)


def _cone_clause_combo(origin: str, broker: str, clauses: tuple[str, ...]) -> Variant:
    def dsl(_identifier: str, coord: tuple[float, float, str]) -> str:
        ra, dec, radius = coord
        return "\n".join([
            f"objects from {origin} via {broker}",
            f"inside ({ra:g}, {dec:g}, {radius})",
            *clauses,
        ])

    def request(_identifier: str, coord: tuple[float, float, str]) -> str:
        ra, dec, radius = coord
        return (
            f"Search {broker.title()} for {origin.upper()} objects around RA {ra:g}, "
            f"Dec {dec:g}, within {radius}, applying the requested constraints."
        )

    ids = LSSTS if origin == "lsst" else ZTFS
    return Variant(dsl, request, origin, broker, (), ids, needs_coordinates=True)


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
        _filter_quality(),
        _where_classification(),
        _match_position(),
        _order_latest(),
        _confirm_classification(),
        _object_product_combo("ztf", "fink", (("lightcurve", "alerce"), ("crossmatch", "antares"))),
        _object_product_combo("ztf", "alerce", (("lightcurve", "fink"), ("classification", "alerce"))),
        _object_product_combo("lsst", "alerce", (("lightcurve", "fink"), ("crossmatch", "antares"))),
        _object_product_combo("lsst", "lasair", (("lightcurve", "fink"), ("classification", "lasair"))),
        _cone_clause_combo("ztf", "fink", ("within 7d", "latest 10")),
        _cone_clause_combo("ztf", "alerce", ("within 30d", "latest 5")),
        _cone_clause_combo("lsst", "lasair", ("latest 10", "order by summary.time.last_mjd asc")),
        _cone_clause_combo("ztf", "fink", ("filter summary@ztf:fink.photometry.r.mag.mean > 18",)),
        _cone_clause_combo("ztf", "alerce", ("where exists classification.best.class",)),
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
    """Return about 100 English phrasings for one canonical DSL.

    The inner sentences are hand-written semantic paraphrases.  The outer
    request frames add natural, low-information context that occurs in real
    chat requests while preserving every astronomy argument.  This gives the
    model much more linguistic coverage without inventing a second DSL target.
    """

    def expand(base: tuple[str, ...]) -> tuple[str, ...]:
        frames = (
            "Astronomy request: {sentence}",
            "Please handle this request: {sentence}",
            "For my analysis, {sentence}",
            "As a follow-up task, {sentence}",
            "I am investigating a transient: {sentence}",
            "For the current observation, {sentence}",
            "In this search, {sentence}",
            "For this catalog query, {sentence}",
            "In the current workflow, {sentence}",
            "The requested operation is: {sentence}",
        )
        unique_base = tuple(dict.fromkeys(base))
        if len(unique_base) == 1:
            sentence = unique_base[0].rstrip(".!?")
            sentence = sentence[:1].lower() + sentence[1:]
            suffixes = (
                "", " for this investigation", " for the current search",
                " from the broker data", " with the requested constraints",
                " as a catalog query", " for follow-up analysis",
                " using the available alert records", " for this transient search",
                " while preserving the stated limits",
            )
            unique_base = tuple(f"{sentence}{suffix}." for suffix in suffixes)
        expanded = tuple(
            frame.format(sentence=sentence)
            for frame in frames
            for sentence in unique_base
        )
        # Keep the first 100 deterministic examples for every DSL group.  The
        # generator later performs a final (request, DSL) deduplication too.
        return tuple(dict.fromkeys(expanded))[:100]

    first, *clauses = dsl.splitlines()
    if "\nfilter detection@ztf:fink.quality.real_bogus" in dsl:
        match = re.search(
            r"inside \(([^,]+), ([^,]+), ([^)]+)\)", dsl
        )
        assert match is not None
        ra, dec, radius = match.groups()
        return expand((
            f"Find ZTF objects from Fink within {radius} of RA {ra} and Dec {dec}, keeping detections with real-bogus score at least 0.8.",
            f"Search Fink for ZTF sources in a {radius} cone at ({ra}, {dec}) and filter for real-bogus >= 0.8.",
            f"Return Fink ZTF objects near RA {ra}, Dec {dec} within {radius} that pass the 0.8 real-bogus threshold.",
            f"Use Fink to find ZTF objects around ({ra}, {dec}), {radius} wide, with quality.real_bogus of at least 0.8.",
            f"Query the {radius} region centered at RA {ra} and Dec {dec} for ZTF detections from Fink rated at least 0.8 real-bogus.",
            f"From Fink, list ZTF objects within {radius} of ({ra}, {dec}) after applying a real-bogus cutoff of 0.8.",
            f"Find ZTF candidates via Fink at ({ra}, {dec}) with search radius {radius}, retaining only scores >= 0.8.",
            f"Look in Fink for ZTF detections no farther than {radius} from RA {ra}, Dec {dec}, where real-bogus is at least 0.8.",
            f"Get the ZTF results from Fink in the {radius} cone around ({ra}, {dec}) and keep high-quality detections above 0.8.",
            f"Search a {radius} area at RA {ra}, Dec {dec} through Fink for ZTF objects passing the real-bogus 0.8 filter.",
        ))
    if "classification@alerce.best.class" in dsl:
        return expand((
            "Find ZTF objects from ALeRCE classified as SN with probability at least 0.5.",
            "Return ALeRCE ZTF sources whose best class is SN and whose confidence is 0.5 or higher.",
            "Search ALeRCE for ZTF objects with an SN classification supported by at least fifty percent probability.",
            "List ZTF candidates from ALeRCE when the predicted class is SN and the probability is >= 0.5.",
            "Using ALeRCE, find ZTF sources labeled SN with best-class probability no lower than 0.5.",
            "Give me ALeRCE ZTF objects identified as supernovae with classification confidence of one half or more.",
            "Query ALeRCE for ZTF objects where the best classification is SN and its probability reaches 0.5.",
            "Select ZTF objects from ALeRCE whose top classification is SN at confidence 0.5 or above.",
            "I need the ALeRCE ZTF candidates classified as SN with a best-probability threshold of 0.5.",
            "Show ZTF sources from ALeRCE for which the best class equals SN and the probability is at least 0.5.",
        ))
    if "match on position inside" in dsl:
        match = re.search(
            r"inside \(([^,]+), ([^,]+), ([^)]+)\)", dsl
        )
        assert match is not None
        ra, dec, radius = match.groups()
        return expand((
            f"Find positional matches between LSST and ZTF through ALeRCE within {radius} of ({ra}, {dec}), using a 1arcsec match radius.",
            f"Search ALeRCE around RA {ra}, Dec {dec} within {radius} for LSST-ZTF pairs separated by at most 1 arcsecond.",
            f"Return LSST and ZTF objects from ALeRCE in the {radius} cone at ({ra}, {dec}) that match within 1arcsec.",
            f"Use ALeRCE to cross-match LSST with ZTF near ({ra}, {dec}), searching {radius} and allowing 1 arcsec positional separation.",
            f"Find linked LSST/ZTF sources via ALeRCE around RA {ra} and Dec {dec}, within {radius}, with a 1 arcsec position match.",
            f"Query the {radius} region centered at ({ra}, {dec}) for ALeRCE positional matches between LSST and ZTF inside 1arcsec.",
            f"List ALeRCE LSST-ZTF associations near ({ra}, {dec}) in a {radius} cone, keeping pairs within one arcsecond.",
            f"Look for LSST and ZTF counterparts through ALeRCE within {radius} of RA {ra}, Dec {dec}, matched at 1arcsec.",
            f"Find objects from both LSST and ZTF in ALeRCE near ({ra}, {dec}) and retain only 1 arcsec positional matches.",
            f"Search ALeRCE for LSST/ZTF position matches in a {radius} area at RA {ra}, Dec {dec}, with separation under 1arcsec.",
        ))
    if "order by summary.time.last_mjd desc" in dsl:
        match = re.search(
            r"inside \(([^,]+), ([^,]+), ([^)]+)\)", dsl
        )
        assert match is not None
        ra, dec, radius = match.groups()
        return expand((
            f"Return the 10 newest ALeRCE ZTF objects within {radius} of RA {ra}, Dec {dec}, ordered by latest observation first.",
            f"Search ALeRCE for ZTF objects around ({ra}, {dec}) within {radius} and sort the latest ten by descending last-observation time.",
            f"List ten recent ZTF sources from ALeRCE in the {radius} cone at ({ra}, {dec}), newest first.",
            f"Use ALeRCE to find the latest 10 ZTF objects near RA {ra}, Dec {dec}, limited to {radius} and ordered by last MJD descending.",
            f"Get the ten most recently observed ALeRCE ZTF objects within {radius} of ({ra}, {dec}).",
            f"Query the {radius} sky region centered at RA {ra}, Dec {dec} for ten ZTF objects, sorting by most recent observation.",
            f"Return up to 10 ZTF candidates through ALeRCE in a {radius} cone at ({ra}, {dec}), with newest records first.",
            f"Find the latest ten ALeRCE ZTF sources no farther than {radius} from ({ra}, {dec}) and order them by last observation descending.",
            f"Show ten ZTF objects from ALeRCE near RA {ra}, Dec {dec}, within {radius}, ranked from newest to oldest.",
            f"For the ALeRCE search centered on ({ra}, {dec}) with radius {radius}, return the ten most recent ZTF objects first.",
        ))
    if "confirm by 2 via fink, lasair" in dsl:
        return expand((
            "Find ZTF objects from Fink whose classification is confirmed by both Fink and Lasair.",
            "Return Fink ZTF candidates with an existing classification confirmed by two brokers: Fink and Lasair.",
            "Search for ZTF sources in Fink and require classification confirmation from Fink and Lasair.",
            "List ZTF objects whose class is present and receives confirmation from both Fink and Lasair.",
            "Use Fink to find ZTF objects, keeping only those with a two-broker classification confirmation from Fink and Lasair.",
            "Query Fink for classified ZTF candidates and confirm each classification through Lasair as well.",
            "Show ZTF sources from Fink where the classification evidence is available from two brokers, Fink plus Lasair.",
            "Find classified ZTF objects via Fink that satisfy a quorum of two confirmations using Fink and Lasair.",
            "I need Fink ZTF objects with classification confirmed by the Fink and Lasair broker results.",
            "Select ZTF candidates from Fink only when their classification can be confirmed by both Fink and Lasair.",
        ))
    if first.startswith("object "):
        _, identifier, _, origin, _, broker = first.split()
        if any("crossmatch via" in clause for clause in clauses) and any(
            "classification" in clause for clause in clauses
        ):
            return expand((
                f"Retrieve the classification, light curve, and crossmatch for {origin.upper()} object {identifier} through {broker.title()}.",
                f"Look up {origin.upper()} source {identifier} in {broker.title()} and return its class, time series, and matching information.",
                f"Using {broker.title()}, get the classification, light curve, and positional crossmatch for {origin.upper()} object {identifier}.",
                f"Return all requested products for {origin.upper()} object {identifier}: classification, light curve, and crossmatch via {broker.title()}.",
                f"For {identifier} from {origin.upper()}, obtain the broker classification together with its light curve and crossmatch.",
                f"Fetch {origin.upper()} object {identifier} through {broker.title()}, including classification, light-curve data, and crossmatch results.",
                f"I need the class, light curve, and counterpart matching for {origin.upper()} source {identifier} from {broker.title()}.",
                f"Can {broker.title()} provide the classification, light curve, and crossmatch associated with {origin.upper()} object {identifier}?",
                f"Query {broker.title()} for {origin.upper()} object {identifier} and include all three products: class, light curve, and crossmatch.",
                f"Provide classification, time-series light-curve, and crossmatch data for {identifier} using {broker.title()}.",
            ))
        if any("crossmatch via" in clause for clause in clauses):
            return expand((
                f"Find {origin.upper()} object {identifier} through {broker.title()} and return its crossmatch and light curve.",
                f"Look up {identifier} from {origin.upper()} using {broker.title()}, including matching information and the light curve.",
                f"For {origin.upper()} source {identifier}, get the crossmatch and light curve via {broker.title()}.",
                f"Use {broker.title()} to retrieve {origin.upper()} object {identifier} with its counterpart match and light curve.",
                f"Return the crossmatch and light curve for {origin.upper()} object {identifier}, using {broker.title()}.",
                f"For {origin.upper()} object {identifier}, obtain matching data plus the light curve with {broker.title()}.",
                f"I need the crossmatch and light curve for {origin.upper()} source {identifier} from {broker.title()}.",
                f"Fetch {origin.upper()} object {identifier} via {broker.title()} and include crossmatch and light-curve data.",
                f"Can {broker.title()} return the counterpart and light curve associated with {origin.upper()} object {identifier}?",
                f"Retrieve both matching information and the light curve for {identifier} through {broker.title()}.",
            ))
        if any("crossmatch" in clause for clause in clauses):
            return expand((
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
            ))
        if any("classification" in clause for clause in clauses) and sum(
            clause.startswith("with ") for clause in clauses
        ) > 1:
            return expand((
                f"Retrieve the classification and light curve for {origin.upper()} object {identifier} through {broker.title()}.",
                f"Look up {origin.upper()} source {identifier} in {broker.title()} and return its class and time series.",
                f"Using {broker.title()}, get both the classification and light curve for {origin.upper()} object {identifier}.",
                f"Return the class and light-curve data for {origin.upper()} object {identifier} via {broker.title()}.",
                f"For {identifier} from {origin.upper()}, obtain the broker classification together with its light curve.",
                f"Fetch {origin.upper()} object {identifier} through {broker.title()}, including classification and light-curve data.",
                f"I need the class and light curve for {origin.upper()} source {identifier} from {broker.title()}.",
                f"Can {broker.title()} provide classification and a light curve for {origin.upper()} object {identifier}?",
                f"Query {broker.title()} for {origin.upper()} object {identifier} and include its class and light curve.",
                f"Provide classification and time-series light-curve data for {identifier} using {broker.title()}.",
            ))
        if any("classification" in clause for clause in clauses):
            return expand((
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
            ))
        return expand((
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
        ))

    if dsl == "objects from ztf via fink\nwithin 7d\nlatest 10":
        return expand((
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
        ))
    match = re.search(r"objects from (.+?) via (\w+)\ninside \(([^,]+), ([^,]+), ([^)]+)\)", dsl)
    if match:
        origins, broker, ra, dec, radius = match.groups()
        origin_words = " and ".join(item.upper() for item in origins.split(", "))
        suffix = "latest 5" in dsl
        number = 5 if suffix else None
        latest = f"the latest {number} " if number else ""
        products = " Return their light curves from Fink and Lasair." if "with lightcurve" in dsl else ""
        return expand((
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
        ))
    return expand((canonical,))


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
