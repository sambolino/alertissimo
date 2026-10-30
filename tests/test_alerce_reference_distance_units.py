"""Endpoint-specific units in recorded ALeRCE client responses; no network."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from alertissimo.api import execute_dsl
from alertissimo.data_layer.execution import ExecutionResult, RegistryEndpointExecutor, TransportResult
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.data_layer.runtime.record_builder import build_portfolios_from_execution
from alertissimo.orchestration.normalization import normalize_workflow_execution


FIXTURES = Path(__file__).parent / "fixtures/alerce/ztf"
PIXEL = "reference_image.nearest_source.pixel_distance"
ANGULAR = "reference_image.nearest_source.separation.total"
CONTRACTS = (
    ("query_detections", "query_detections", PIXEL, ANGULAR),
    ("query_lightcurve", "query_lightcurve.detections", PIXEL, ANGULAR),
    ("query_forced_photometry", "query_forced_photometry", ANGULAR, PIXEL),
)


def fixture(endpoint):
    return json.loads((FIXTURES / f"{endpoint}.json").read_text())


def payload(endpoint, row):
    return {"detections": [row], "non_detections": []} if endpoint == "query_lightcurve" else [row]


def first_row(endpoint):
    data = fixture(endpoint)
    return data["detections"][0] if endpoint == "query_lightcurve" else data[0]


def build(endpoint, data):
    return build_portfolios_from_execution(ExecutionResult(
        payload=data,
        execution_provenance=InternalExecutionProvenance(
            InternalExecutionId(f"units:{endpoint}"), "alerce", "ztf", endpoint,
            params={"oid": "ZTF18abbuksn", "survey": "ztf", "format": "json"},
        ),
    ), validate_semantic_model=True)


@pytest.mark.parametrize("endpoint,branch,expected,absent", CONTRACTS)
def test_captured_values_keep_their_endpoint_unit_and_source(endpoint, branch, expected, absent):
    row = first_row(endpoint)
    data = payload(endpoint, row)
    before = deepcopy(data)
    portfolios = build(endpoint, data)
    record, = [r for p in portfolios for r in p.records if r.semantic_type == "measurement@ztf:alerce"]
    assert record.get(expected) == row["distnr"]
    assert absent not in record.fields
    assert record.internal_source.payload_key == branch
    assert record.internal_source.payload_index == 0
    assert record.get("time.mjd") == row["mjd"]
    assert data == before


@pytest.mark.parametrize("endpoint,branch,expected,absent", CONTRACTS)
@pytest.mark.parametrize("value", [0.0, -999.0, None, "missing"])
def test_missing_zero_and_sentinel_values_are_not_converted_between_units(endpoint, branch, expected, absent, value):
    row = first_row(endpoint)
    if value == "missing":
        row.pop("distnr")
    else:
        row["distnr"] = value
    data = payload(endpoint, row)
    before = deepcopy(data)
    record, = [r for p in build(endpoint, data) for r in p.records if r.semantic_type == "measurement@ztf:alerce"]
    if value == "missing":
        assert expected not in record.fields
    else:
        assert record.get(expected) == value
    assert absent not in record.fields
    assert data == before


def test_enrichment_retains_pixel_and_angular_evidence_in_their_own_measurements():
    class ReplayTransport:
        def __init__(self):
            # Recorded subsets exercise the public family path; they make no
            # claim of a complete lightcurve or classifier population.
            self.responses = {
                "query_object": fixture("query_object"),
                "query_probabilities": fixture("query_probabilities")[:1],
                "query_lightcurve": payload("query_lightcurve", first_row("query_lightcurve")),
                "query_forced_photometry": [first_row("query_forced_photometry")],
            }
            self.calls = []
        def execute(self, spec, params, headers=None):
            assert (spec.broker, spec.origin) == ("alerce", "ztf")
            assert params["survey"] == "ztf" and params["oid"] == "ZTF18abbuksn"
            self.calls.append(spec.endpoint)
            return TransportResult(deepcopy(self.responses[spec.endpoint]))

    transport = ReplayTransport()
    result = execute_dsl("objects ZTF18abbuksn from ztf via alerce\nwith enrichment\n",
                         graph=build_capability_graph(),
                         executor=RegistryEndpointExecutor(transports={"python_client": transport}),
                         continue_from=None)
    assert set(transport.calls) == {"query_object", "query_probabilities", "query_lightcurve", "query_forced_photometry"}
    assert len(transport.calls) == 4
    for portfolios in (result.portfolios, normalize_workflow_execution(result.staged.execution).steps[-1].portfolios):
        measurements = [r for p in portfolios for r in p.records if r.semantic_type == "measurement@ztf:alerce"]
        ordinary, = [r for r in measurements if r.internal_source.payload_key == "query_lightcurve.detections"]
        forced, = [r for r in measurements if r.internal_source.payload_key == "query_forced_photometry"]
        assert ordinary.get(PIXEL) == first_row("query_lightcurve")["distnr"]
        assert ANGULAR not in ordinary.fields
        assert forced.get(ANGULAR) == first_row("query_forced_photometry")["distnr"]
        assert PIXEL not in forced.fields
