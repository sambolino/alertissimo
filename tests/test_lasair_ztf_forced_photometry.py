"""Lasair's captured forced series stays separate, signed and identity-bound."""

from copy import deepcopy
from itertools import count
import json
from pathlib import Path

import pytest
import yaml

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.data_layer.runtime.record_builder import build_portfolios_from_execution
from alertissimo.orchestration.normalization import summary_object_identity
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import WorkflowExecutionError


FIXTURES = Path(__file__).parent / "fixtures/lasair/ztf"
PROVIDER = Path(__file__).parents[1] / "alertissimo/data_layer/providers/lasair/ztf"
OBJECT_ID = "ZTF17aaabasp"
COLLECTION = "lightcurve@ztf:lasair.forced_photometry_points"
BANDS = {1: "g", 2: "r", 3: "i"}


def captured(endpoint):
    return json.loads((FIXTURES / f"{endpoint}_{OBJECT_ID}.json").read_text())


def execution(endpoint, payload, params=None):
    return ExecutionResult(payload=payload, execution_provenance=InternalExecutionProvenance(
        InternalExecutionId("forced:capture:" + endpoint), "lasair", "ztf", endpoint, params=params or {},
    ))


def series(portfolio, field="forced_photometry_points"):
    return tuple(point for record in portfolio.records if record.semantic_type == "lightcurve@ztf:lasair"
                 for point in record.fields.get(field, ()))


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


@pytest.mark.parametrize("endpoint", ["object", "lightcurves"])
def test_capture_maps_all_688_epochs_without_inventing_magnitudes_or_limits(endpoint):
    payload = captured(endpoint)
    root = payload[0] if endpoint == "lightcurves" else payload
    parameter = "objectIds" if endpoint == "lightcurves" else "objectId"
    (portfolio,) = build_portfolios_from_execution(
        execution(endpoint, payload, params={parameter: OBJECT_ID}), validate_semantic_model=True,
    )
    points = series(portfolio)
    assert summary_object_identity(portfolio) == ("ztf", OBJECT_ID)
    assert len(points) == len(root["forcedphot"]) == 688
    assert len(series(portfolio, "points")) == (len(root["candidates"]) if endpoint == "lightcurves" else 0)
    missing = negative = 0
    for raw, point in zip(root["forcedphot"], points):
        band = BANDS[raw["fid"]]
        flux = f"forced_photometry.{band}.flux"
        assert point["identity.object_id"] == raw["objectid"]
        assert point["time.mjd"] == pytest.approx(raw["jd"] - 2400000.5)
        assert point[f"calibration.{band}.zero_point"] == raw["magzpsci"]
        if raw["forcediffimflux"] == -99999:
            missing += 1
            assert flux not in point and flux + ".error" not in point
        else:
            assert point[flux] == raw["forcediffimflux"]
            assert point[flux + ".error"] == raw["forcediffimfluxunc"]
            negative += raw["forcediffimflux"] < 0
        assert not any(".mag" in path or "upper_limit" in path or ".psf.flux" in path for path in point)
        assert not any("reference_image" in path or "position." in path for path in point)
    assert missing == 256 and negative == 278


def test_unbound_lightcurve_receipt_does_not_infer_a_summary_from_point_identity():
    # Controlled envelope around a captured row, with no target-bound request.
    raw = next(row for row in captured("object")["forcedphot"] if row["forcediffimflux"] != -99999)
    payload = [{"objectId": OBJECT_ID, "forcedphot": [raw]}]
    (portfolio,) = build_portfolios_from_execution(
        execution("lightcurves", payload), validate_semantic_model=True,
    )
    (point,) = series(portfolio)
    assert point["identity.object_id"] == OBJECT_ID
    assert summary_object_identity(portfolio) is None


def test_captured_forced_fields_are_mapped_or_explicit_reference_coordinate_debt():
    mappings = yaml.safe_load((PROVIDER / "mappings.yaml").read_text())
    debt = yaml.safe_load((PROVIDER / "unmapped_fields.yaml").read_text())
    mapped = {ref for refs in mappings["mappings"].values() for ref in refs}
    unmapped = {key: value for entry in debt["unmapped"] for key, value in entry.items()}
    for key in ("forcedphot", "lightcurve_forcedphot"):
        assert {f"{key}#{raw}" for raw in captured("object")["forcedphot"][0]} <= mapped | unmapped.keys()
        for raw in ("ranr", "decnr"):
            ref = f"{key}#{raw}"
            assert ref not in mapped
            assert "nearest source in the reference-image" in unmapped[ref]["candidate_meaning"]


class Executor:
    """Controlled envelopes with captured FP rows; no network and no credentials."""

    def __init__(self, *, rows=None, fail=False, drop=()):
        self.calls, self.sequence, self.fail = [], count(), fail
        sample = next(row for row in captured("object")["forcedphot"] if -99999 < row["forcediffimflux"] < 0)
        self.rows = {OBJECT_ID: [sample]} if rows is None else rows
        self.drop = set(drop)

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        params = deepcopy(dict(params or {}))
        self.calls.append((broker, endpoint, params))
        assert origin == "ztf"
        if broker == "alerce":
            assert endpoint == "query_object"
            payload = {"oid": params["oid"], "meanra": 10.0, "meandec": 20.0}
        else:
            assert broker == "lasair" and endpoint in ("object", "lightcurves")
            if self.fail and endpoint == "lightcurves":
                raise RuntimeError("controlled forced-series failure")
            ids = params["objectIds"].split(",") if endpoint == "lightcurves" else [params["objectId"]]
            payload = []
            for object_id in ids:
                if object_id in self.drop:
                    continue
                root = {"objectId": object_id, "candidates": []}
                if object_id in self.rows:
                    root["forcedphot"] = deepcopy(self.rows[object_id])
                    if isinstance(root["forcedphot"], list):
                        for row in root["forcedphot"]:
                            if row:
                                row["objectid"] = object_id
                payload.append(root)
            if endpoint == "object":
                (payload,) = payload
        return ExecutionResult(payload=payload, execution_provenance=InternalExecutionProvenance(
            InternalExecutionId(f"forced:public:{next(self.sequence)}"), broker, origin, endpoint, params=params,
        ))


def program(ids=(OBJECT_ID,)):
    # An identity-only lookup avoids asking for the same series twice.
    return ("objects " + ", ".join(ids) + " from ztf via alerce\n"
            "with lightcurve.forced_photometry_points via lasair\n")


def test_component_and_reference_use_the_existing_single_lightcurve_call(graph):
    for source in (program(), program().replace("lightcurve.forced_photometry_points", "lightcurve")
                   + f"filter count({COLLECTION} where time.mjd > 60000) >= 1"):
        validated = validate_dsl(source, graph=graph, continue_from=None)
        assert validated.is_valid and validated.is_runnable, validated.lowering_error
        plans = plan_workflow(validated.compilation.workflow, graph).steps[1].endpoint_plans
        assert [(p.endpoint, p.required) for p in plans] == [("lightcurves", True)]
        executor = Executor()
        result = execute_dsl(source, graph=graph, executor=executor, continue_from=None)
        assert len(result.portfolios) == 1
        assert [endpoint for _, endpoint, _ in executor.calls] == ["query_object", "lightcurves"]
        assert len(series(result.portfolios[0])) == 1


def test_required_empty_child_is_known_empty_and_continuation_does_not_call_again(graph):
    executor = Executor(rows={OBJECT_ID: []})
    first = execute_dsl(program(), graph=graph, executor=executor, continue_from=None)
    assert len(first.portfolios) == 1
    calls, before = deepcopy(executor.calls), first.to_dict()
    selected = execute_dsl(f"filter count({COLLECTION}) = 0", graph=graph, executor=executor, continue_from=first)
    assert len(selected.portfolios) == 1 and executor.calls == calls
    assert first.to_dict() == before


def test_batched_empty_evidence_is_bound_to_its_parent_object(graph):
    executor = Executor()
    sample = deepcopy(executor.rows[OBJECT_ID])
    executor.rows = {"ZTF-synthetic-empty": [], "ZTF-synthetic-present": sample}
    source = program(tuple(executor.rows))
    empty = execute_dsl(source + f"filter count({COLLECTION}) = 0", graph=graph,
                        executor=executor, continue_from=None)
    assert [summary_object_identity(p)[1] for p in empty.portfolios] == ["ZTF-synthetic-empty"]
    present = execute_dsl(source + f"filter count({COLLECTION}) >= 1", graph=graph,
                          executor=executor, continue_from=None)
    assert [summary_object_identity(p)[1] for p in present.portfolios] == ["ZTF-synthetic-present"]


@pytest.mark.parametrize("shape", ["missing", "null", "malformed", "omitted_parent"])
def test_missing_or_malformed_child_is_not_an_empty_receipt(graph, shape):
    rows = {} if shape == "missing" else {OBJECT_ID: None if shape == "null" else [{}]}
    executor = Executor(rows=rows, drop=(OBJECT_ID,) if shape == "omitted_parent" else ())
    result = execute_dsl(program() + f"filter count({COLLECTION}) = 0", graph=graph,
                         executor=executor, continue_from=None)
    assert result.portfolios == ()


def test_required_series_failure_is_visible(graph):
    with pytest.raises(WorkflowExecutionError, match="controlled forced-series failure"):
        execute_dsl(program(), graph=graph, executor=Executor(fail=True), continue_from=None)


def test_lookup_material_can_be_filtered_without_retrieving_the_series_again(graph):
    executor = Executor()
    source = f"object {OBJECT_ID} from ztf via lasair\nfilter count({COLLECTION}) >= 1"
    result = execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    assert len(result.portfolios) == 1
    assert [endpoint for _, endpoint, _ in executor.calls] == ["object"]


@pytest.mark.parametrize("flux", [0.0, -2.0, None, -99999.0])
def test_zero_and_negative_flux_remain_values_but_null_and_sentinel_do_not(flux):
    payload = [{"objectId": OBJECT_ID, "forcedphot": [{
        "objectid": OBJECT_ID, "jd": 2460000.5, "fid": 1,
        "forcediffimflux": flux, "forcediffimfluxunc": 0.2, "magzpsci": 26.0,
    }]}]
    (portfolio,) = build_portfolios_from_execution(execution("lightcurves", payload), validate_semantic_model=True)
    (point,) = series(portfolio)
    path = "forced_photometry.g.flux"
    if flux is None or flux == -99999:
        assert path not in point
    else:
        assert point[path] == flux
    assert point[path + ".error"] == 0.2
    assert point["calibration.g.zero_point"] == 26.0


def test_two_actual_series_occurrences_remain_ambiguous_instead_of_pooling(graph):
    source = (f"object {OBJECT_ID} from ztf via lasair\n"
              "with lightcurve.forced_photometry_points\n"
              f"filter count({COLLECTION}) >= 1")
    result = execute_dsl(source, graph=graph, executor=Executor(), continue_from=None)
    assert result.portfolios == ()
    assert any("ambiguous_product" in warning for step in result.run.steps for warning in step.warnings)
