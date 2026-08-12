"""Authoritative checks for the observed Lasair/ZTF cone and Sherlock payloads."""

from __future__ import annotations

from itertools import count
import json
from pathlib import Path

import yaml

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
    InternalPortfolioId,
    InternalRecordId,
)
from alertissimo.data_layer.runtime.record_builder import build_portfolio_from_execution
from tools.audit_payload_mapping_coverage import audit_payload


FIXTURES = Path(__file__).parent / "fixtures" / "lasair" / "ztf"
MAPPINGS = (
    Path(__file__).parents[1]
    / "alertissimo/data_layer/providers/lasair/ztf/mappings.yaml"
)
UNMAPPED = (
    Path(__file__).parents[1]
    / "alertissimo/data_layer/providers/lasair/ztf/unmapped_fields.yaml"
)


def _fixture(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _build(endpoint: str, payload):
    execution_id = InternalExecutionId(f"execution:fixture:{endpoint}")
    ids = count()
    return build_portfolio_from_execution(
        ExecutionResult(
            payload=payload,
            execution_provenance=InternalExecutionProvenance(
                internal_execution_id=execution_id,
                broker="lasair",
                origin="ztf",
                endpoint=endpoint,
            ),
        ),
        mappings_path=MAPPINGS,
        internal_portfolio_id=InternalPortfolioId("portfolio:fixture"),
        record_id_factory=lambda: InternalRecordId(f"record:{next(ids)}"),
        validate_semantic_model=True,
    )


def test_authoritative_cone_is_fully_accounted_without_fabricating_separation():
    payload = _fixture("cone")
    assert payload == [{"object": "ZTF23aabplmy", "separation": 0.763}]
    report = audit_payload(
        payload,
        broker="lasair",
        origin="ztf",
        endpoint="cone",
        payload_file=str(FIXTURES / "cone.json"),
    )
    assert "Unaccounted leaves: 0" in report

    portfolio = _build("cone", payload)
    summaries = [r for r in portfolio.records if r.semantic_type == "summary@ztf:lasair"]
    assert len(summaries) == 1
    assert dict(summaries[0].fields) == {"identity.object_id": "ZTF23aabplmy"}
    assert not any("separation" in field for field in summaries[0].fields)


def test_authoritative_sherlock_position_is_fully_accounted_and_normalized():
    payload = _fixture("sherlock_position")
    assert len(payload["crossmatches"]) == 4
    report = audit_payload(
        payload,
        broker="lasair",
        origin="ztf",
        endpoint="sherlock_position",
        payload_file=str(FIXTURES / "sherlock_position.json"),
    )
    assert "Unaccounted leaves: 0" in report

    portfolio = _build("sherlock_position", payload)
    classifications = [
        r for r in portfolio.records if r.semantic_type == "classification@sherlock:lasair"
    ]
    assert len(classifications) == 1
    assert classifications[0].fields["best.class"] == "SN"

    by_type = {r.semantic_type: r for r in portfolio.records if r.semantic_type.startswith("crossmatch@")}
    assert {
        "crossmatch@sdss_2mass_ps1:lasair",
        "crossmatch@twomass:lasair",
        "crossmatch@panstarrs:lasair",
        "crossmatch@sdss:lasair",
    } <= set(by_type)

    combined = by_type["crossmatch@sdss_2mass_ps1:lasair"].fields
    assert combined["identity.object_id"] == "1237673709862061782"
    assert combined["separation.total"] == 1.5719427375338366
    assert combined["separation.north"] == -1.15164
    assert combined["separation.east"] == 1.06992
    assert combined["photometry.J.mag"] == 17.007

    twomass = by_type["crossmatch@twomass:lasair"].fields
    assert twomass["identity.object_id"] == "08193126-0601149"


def test_sherlock_z_and_photoz_are_not_collapsed_into_one_redshift_measurement():
    payload = {
        "classifications": {},
        "crossmatches": [
            {
                "catalogue_table_name": "SDSS DR12 PhotoObjAll Table",
                "catalogue_object_id": "example",
                "z": 0.03,
                "photoZ": 0.12,
                "photoZErr": 0.01,
            }
        ],
    }
    portfolio = _build("sherlock_position", payload)
    record = next(r for r in portfolio.records if r.semantic_type == "crossmatch@sdss:lasair")
    fields = dict(record.fields)
    assert fields["redshift.value"] == 0.03
    assert "redshift.error" not in fields


def test_photoz_and_merged_rank_are_explicit_debt_not_semantic_fallbacks():
    mappings = yaml.safe_load(MAPPINGS.read_text(encoding="utf-8"))
    unmapped = yaml.safe_load(UNMAPPED.read_text(encoding="utf-8"))
    mapped_refs = {ref for refs in mappings["mappings"].values() for ref in refs}
    debt_refs = {next(iter(entry)) for entry in unmapped["unmapped"]}

    for ref in (
        "object#sherlock.photoZ",
        "object#sherlock.photoZErr",
        "sherlock_position_crossmatches#photoZ",
        "sherlock_position_crossmatches#photoZErr",
        "sherlock_objects_crossmatches#photoZ",
        "sherlock_objects_crossmatches#photoZErr",
        "sherlock_position_crossmatches#merged_rank",
        "sherlock_objects_crossmatches#merged_rank",
    ):
        assert ref not in mapped_refs
        assert ref in debt_refs


def test_unknown_catalogue_names_are_not_collapsed_to_unknown_producer():
    document = yaml.safe_load(MAPPINGS.read_text(encoding="utf-8"))
    spec = document["transforms"]["crossmatch@{producer}:lasair.provenance.producer.id"][
        "object#sherlock.catalogue_table_name"
    ]
    assert spec["map"]["SDSS"] == "sdss"
    assert "default" not in spec
