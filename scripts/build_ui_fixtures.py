#!/usr/bin/env python3
"""Build the offline, Portfolio-only corpus used to develop the UI."""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from collections import Counter
from itertools import count
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alertissimo.data_layer.execution import ExecutionResult  # noqa: E402
from alertissimo.data_layer.representations import (  # noqa: E402
    InternalExecutionId,
    InternalExecutionProvenance,
    InternalPortfolioId,
    InternalRecordId,
    Portfolio,
    SemanticRecord,
)
from alertissimo.data_layer.runtime.record_builder import build_portfolio_from_execution  # noqa: E402
from alertissimo.data_layer.runtime.serialization import portfolio_to_json  # noqa: E402
from alertissimo.data_layer.semantic_model.validation import (  # noqa: E402
    validate_portfolio_against_semantic_model,
)

FIXTURES = ROOT / "tests" / "fixtures"
PROVIDERS = ROOT / "alertissimo" / "data_layer" / "providers"
ONTOLOGY = ROOT / "alertissimo" / "data_layer" / "semantic_model" / "ontology.yaml"
DEFAULT_OUTPUT = ROOT / ".ui-fixtures" / "portfolios"

# filename: broker, survey, [(endpoint, frozen payload)]
SPECS = {
    "lsst_alerce_170587117485817955.json": ("alerce", "lsst", [
        ("query_objects", FIXTURES / "alerce/lsst/query_objects.json"),
        ("query_object", FIXTURES / "alerce/lsst/query_object.json"),
        ("query_detections", FIXTURES / "alerce/lsst/query_detections.json"),
        ("query_forced_photometry", FIXTURES / "alerce/lsst/query_forced_photometry.json"),
        ("query_probabilities", FIXTURES / "alerce/lsst/query_probabilities.json"),
    ]),
    "lsst_fink_170587117485817955.json": ("fink", "lsst", [
        ("objects", FIXTURES / "fink/lsst/objects.json"),
        ("sources", FIXTURES / "fink/lsst/sources.json"),
        ("fp", FIXTURES / "fink/lsst/fp.json"),
    ]),
    "lsst_antares_170587117485817955.json": ("antares", "lsst", [
        ("get_by_lsst_dia_object_id", FIXTURES / "antares/lsst/get_by_lsst_dia_object_id.json"),
    ]),
    "lsst_lasair_313761042336317573.json": ("lasair", "lsst", [
        ("object", FIXTURES / "lasair/lsst/capture_20260813T140948Z/object_with_context.json"),
    ]),
    "ztf_alerce_ZTF18abbuksn.json": ("alerce", "ztf", [
        ("query_object", FIXTURES / "alerce/ztf/query_object.json"),
        ("query_detections", FIXTURES / "alerce/ztf/query_detections.json"),
        ("query_non_detections", FIXTURES / "alerce/ztf/query_non_detections.json"),
        ("query_forced_photometry", FIXTURES / "alerce/ztf/query_forced_photometry.json"),
        ("query_probabilities", FIXTURES / "alerce/ztf/query_probabilities.json"),
    ]),
    "ztf_fink_ZTF21abfmbix.json": ("fink", "ztf", [
        ("objects", FIXTURES / "fink/ztf/objects_withupperlim.json"),
    ]),
    "ztf_antares_ZTF20aafqubg.json": ("antares", "ztf", [
        ("get_by_ztf_object_id", FIXTURES / "antares/ztf/get_by_ztf_object_id.json"),
    ]),
    "ztf_lasair_ZTF20acpwljl.json": ("lasair", "ztf", [
        ("object", FIXTURES / "lasair/ztf/capture_20260813T110413Z/object_default.json"),
    ]),
    "lsst_fink_313936986529333309.json": ("fink", "lsst", [
        ("objects", FIXTURES / "ui/sources/fink_pair/lsst_objects.json"),
        ("sources", FIXTURES / "ui/sources/fink_pair/lsst_sources.json"),
        ("fp", FIXTURES / "ui/sources/fink_pair/lsst_fp.json"),
    ]),
    "ztf_fink_ZTF18acurdih.json": ("fink", "ztf", [
        ("objects", FIXTURES / "ui/sources/fink_pair/ztf_objects.json"),
    ]),
}


def _portfolio_id(name: str) -> InternalPortfolioId:
    return InternalPortfolioId(f"portfolio:ui:{name.removesuffix('.json')}")


def compose(name: str, portfolios: list[Portfolio]) -> Portfolio:
    """Concatenate independently normalized components without inventing edges."""
    result = Portfolio(
        internal_portfolio_id=_portfolio_id(name),
        records=tuple(record for item in portfolios for record in item.records),
        executions=tuple(execution for item in portfolios for execution in item.executions),
        edges=tuple(edge for item in portfolios for edge in item.edges),
    )
    validate_portfolio_against_semantic_model(result)
    return result


def _build_real(name: str, broker: str, survey: str, inputs: list[tuple[str, Path]]) -> Portfolio:
    components = []
    for component, (endpoint, path) in enumerate(inputs):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if broker == "antares" and endpoint.startswith("get_by_"):
            # ANTARES freezes the client-visible locus and its lazy relationships
            # independently. Recreate that one endpoint result before normalization.
            payload = copy.deepcopy(payload)
            fixture_dir = path.parent
            payload["alerts"] = json.loads(
                (fixture_dir / "alerts.json").read_text(encoding="utf-8")
            )
            payload["catalog_objects"] = json.loads(
                (fixture_dir / "catalog_objects.json").read_text(encoding="utf-8")
            )
        execution_id = InternalExecutionId(f"execution:ui:{name}:{component}:{endpoint}")
        ids = count()
        execution = ExecutionResult(payload=payload, execution_provenance=InternalExecutionProvenance(
            internal_execution_id=execution_id, broker=broker, origin=survey,
            endpoint=endpoint, params={}, status="frozen-fixture",
        ))
        components.append(build_portfolio_from_execution(
            execution, mappings_path=PROVIDERS / broker / survey / "mappings.yaml",
            internal_portfolio_id=_portfolio_id(f"{name}:{component}"),
            record_id_factory=lambda c=component, ids=ids: InternalRecordId(
                f"record:ui:{name}:{c}:{next(ids)}"
            ), validate_semantic_model=True,
        ))
    return compose(name, components)


def portfolio_families() -> tuple[str, ...]:
    """Mechanically read the first-level record references in ``<portfolio>``."""
    source = ONTOLOGY.read_text(encoding="utf-8")
    block = source.split("<portfolio>:", 1)[1]
    return tuple(re.findall(r"^  \$refs: <([^>]+)>", block, re.MULTILINE))


def _gallery(real: list[Portfolio]) -> Portfolio:
    grouped = Counter(r.semantic_type.split("@", 1)[0] for p in real for r in p.records)
    missing = [family for family in portfolio_families() if grouped[family] < 2]
    examples = {
        "lightcurve": (
            {"provenance.producer.name": "synthetic UI fixture", "detection_count": 3,
             "g.points": [{"time.mjd": 61000.1, "photometry.g.psf.mag": 20.1},
                          {"time.mjd": 61001.2, "photometry.g.psf.mag": 19.7}],
             "r.points": [{"time.mjd": 61000.5, "photometry.r.psf.mag": 19.4}]},
            {"provenance.producer.name": "synthetic UI fixture", "detection_count": 3,
             "i.points": [{"time.mjd": 62010.0, "photometry.i.psf.mag": 18.6},
                          {"time.mjd": 62011.0, "photometry.i.psf.mag": 18.4},
                          {"time.mjd": 62012.0, "photometry.i.psf.mag": 18.1}]},
        ),
        "spectrum": (
            {"identity.object_id": "UI-SPECTRUM-1", "identity.source_id": "spec-1",
             "time.mjd": 61002.25, "provenance.producer.name": "synthetic UI fixture",
             "instrument_mode": "low-resolution grism", "wavelength_min": 3800.0,
             "wavelength_max": 9200.0, "signal_to_noise": 18.0},
            {"identity.object_id": "UI-SPECTRUM-2", "identity.source_id": "spec-2",
             "time.mjd": 62020.5, "provenance.producer.name": "synthetic UI fixture",
             "instrument_mode": "fiber spectroscopy", "resolving_power": 2500.0,
             "wavelength_min": 4500.0, "wavelength_max": 8000.0,
             "signal_to_noise": 32.0},
        ),
        "data_product": (
            {"identity.object_id": "UI-DATA-PRODUCT-1", "type": "cutout",
             "role": "science", "format": "fits",
             "uri": "fixture://ui/cutout-science.fits"},
            {"identity.object_id": "UI-DATA-PRODUCT-2", "type": "table",
             "role": "derived", "format": "parquet",
             "uri": "fixture://ui/measurements.parquet"},
        ),
        "survey": (
            {"identity.object_id": "UI-SURVEY-SNAPSHOT-1", "snapshot_key": "ui-night-1",
             "time.snapshot_datetime": "2026-01-15T00:00:00Z", "alert_count": 240,
             "object_count": 75, "filter_counts": {"g": 100, "r": 140}},
            {"identity.object_id": "UI-SURVEY-SNAPSHOT-2", "snapshot_key": "ui-night-2",
             "time.snapshot_datetime": "2026-01-16T00:00:00Z", "alert_count": 310,
             "object_count": 92, "class_distribution": {"SN": 21, "AGN": 14}},
        ),
    }
    records = tuple(
        SemanticRecord(
            InternalRecordId(f"record:ui:gallery:{family}:{index}"),
            f"{family}@fixture:ui",
            examples.get(family, (
                {"identity.object_id": f"UI-{family.upper()}-1", "provenance.producer.name":
                 "synthetic UI fixture"},
                {"identity.object_id": f"UI-{family.upper()}-2", "provenance.producer.name":
                 "synthetic UI fixture"},
            ))[index],
        )
        for family in missing for index in range(2)
    )
    result = Portfolio(_portfolio_id("semantic_gallery_synthetic"), records=records)
    validate_portfolio_against_semantic_model(result)
    return result


def _single(name: str, record: SemanticRecord, source: Portfolio) -> Portfolio:
    executions = tuple(e for e in source.executions if record.internal_source and
                       e.internal_execution_id == record.internal_source.internal_execution_id)
    return Portfolio(_portfolio_id(name), records=(record,), executions=executions)


def build_corpus(output: Path = DEFAULT_OUTPUT) -> dict[str, Portfolio]:
    output.mkdir(parents=True, exist_ok=True)
    corpus = {name: _build_real(name, *spec) for name, spec in SPECS.items()}
    corpus["multibroker_lsst_170587117485817955.json"] = compose(
        "multibroker_lsst_170587117485817955.json", [corpus[name] for name in (
            "lsst_alerce_170587117485817955.json", "lsst_fink_170587117485817955.json",
            "lsst_antares_170587117485817955.json")])
    corpus["multisurvey_fink_313936986529333309__ZTF18acurdih.json"] = compose(
        "multisurvey_fink_313936986529333309__ZTF18acurdih.json", [
            corpus["lsst_fink_313936986529333309.json"], corpus["ztf_fink_ZTF18acurdih.json"]])
    source = corpus["lsst_alerce_170587117485817955.json"]
    corpus["minimal_summary_real.json"] = _single("minimal_summary_real", next(
        r for r in source.records if r.semantic_type.startswith("summary@")), source)
    corpus["minimal_detection_real.json"] = _single("minimal_detection_real", next(
        r for r in source.records if r.semantic_type.startswith("detection@")), source)
    corpus["semantic_gallery_synthetic.json"] = _gallery(list(corpus.values()))
    for name, portfolio in corpus.items():
        (output / name).write_text(portfolio_to_json(portfolio) + "\n", encoding="utf-8")
    return corpus


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    build_corpus(args.output)


if __name__ == "__main__":
    main()
