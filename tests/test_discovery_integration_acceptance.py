"""Named integration regressions over frozen response shapes; no provider calls.

Fink transports route unchanged recorded rows as either discovery or history.
ALeRCE probabilities are unchanged; its summary ID is rebound only to reproduce
the original report's lookup. These fixture routes are not new live captures.
"""

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import RegistryEndpointExecutor, TransportResult
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.data_layer.runtime.serialization import portfolio_to_dict
from alertissimo.orchestration.normalization import summary_object_identity
from alertissimo.orchestration.runtime import WorkflowExecutionError


FIXTURES = Path(__file__).parent / "fixtures"
SN_NOW = datetime(2021, 7, 2, tzinfo=timezone.utc)
IA_NOW = datetime(2021, 11, 25, tzinfo=timezone.utc)
SN_QUERY = ('objects from ztf via fink\nwithin 7d\n'
            'where classification.best.class = "SN candidate"\n')
IA_QUERY = SN_QUERY.replace('"SN candidate"', '"Early SN Ia candidate"')


def captured(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def identities(portfolios):
    return {summary_object_identity(p) for p in portfolios}


class FinkReplay:
    def __init__(self, discovery, histories=None, *, interrupted=False):
        self.discovery = deepcopy(discovery)
        self.histories = deepcopy(discovery if histories is None else histories)
        self.interrupted = interrupted
        self.calls = []

    def execute(self, spec, params, headers=None):
        assert (spec.broker, spec.origin, spec.method) == ("fink", "ztf", "GET")
        self.calls.append((spec.endpoint, deepcopy(dict(params))))
        if spec.endpoint == "latests":
            if self.interrupted:
                raise RuntimeError("controlled interrupted discovery")
            rows = self.discovery
        else:
            assert spec.endpoint == "objects"
            requested = set(params["objectId"].split(","))
            rows = [row for row in self.histories if row["i:objectId"] in requested]
        return TransportResult(deepcopy(rows), status_code=200, content_type="application/json")


def run_fink(source, transport, graph, *, now=IA_NOW):
    return execute_dsl(source, graph=graph, continue_from=None, reference_time=now,
                       executor=RegistryEndpointExecutor(transports={"rest": transport}))


@pytest.mark.parametrize("classifier", [None, "lc_classifier"], ids=["unconstrained", "named-classifier"])
def test_alerce_classification_original_reports_keep_all_selected_versions(graph, monkeypatch, classifier):
    probabilities = captured("alerce/ztf/query_probabilities.json")
    summary = captured("alerce/ztf/query_object.json")
    calls = []

    class StrictRecordedClient:
        def query_object(self, oid, format="json", survey=None):
            assert oid == "ZTF21abfmbix" and survey == "ztf" and format == "json"
            calls.append("query_object")
            return {**deepcopy(summary), "oid": oid}

        # The inspected native signature has no classifier keyword. Selection
        # must follow retrieval, rather than silently filtering this fixture.
        def query_probabilities(self, oid, format="json", survey=None, index=None, sort=None):
            assert oid == "ZTF21abfmbix" and survey == "ztf" and format == "json"
            calls.append("query_probabilities")
            return deepcopy(probabilities)

    monkeypatch.setitem(sys.modules, "alerce.core", SimpleNamespace(Alerce=StrictRecordedClient))
    selector = "" if classifier is None else f" from {classifier}"
    source = f"objects ZTF21abfmbix from ztf via alerce\nwith classification{selector} via alerce\n"
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    assert calls == []
    result = execute_dsl(source, graph=graph, executor=RegistryEndpointExecutor(), continue_from=None)
    assert calls == ["query_object", "query_probabilities"]
    assert identities(result.portfolios) == {("ztf", "ZTF21abfmbix")}
    selected = [row for row in probabilities if classifier is None or row["classifier_name"] == classifier]
    expected = Counter((r["classifier_name"], r["classifier_version"], r["class_name"], r["probability"], r["ranking"])
                       for r in selected)
    actual = Counter()
    for p in result.portfolios:
        for record in p.records:
            if not record.semantic_type.startswith("classification@"):
                continue
            for path in record.fields:
                if path.startswith("assessment.") and path.endswith(".class"):
                    prefix = path.removesuffix(".class")
                    actual[(record.get("provenance.producer.name"), record.get("provenance.producer.version"),
                            record.get(path), record.get(f"{prefix}.probability"), record.get(f"{prefix}.rank"))] += 1
    assert actual == expected and actual
    probability_plan, = result.run.steps[1].endpoint_plans
    assert probability_plan.endpoint == "query_probabilities"
    assert "classifier" not in probability_plan.request_params
    assert "classifier" not in probability_plan.parameter_sources
    assert result.staged.execution.steps[1].executions[0].payload == probabilities


def test_fink_class_time_original_seven_day_query_matches_direct_science_values(graph):
    histories = captured("fink/ztf/objects_core.json")
    # Controlled routing of the recorded SN rows through the class endpoint.
    end_jd = 2459397.5  # SN_NOW; the scientific interval is closed at both ends.
    discovery = [r for r in histories if end_jd - 7 <= r["i:jd"] <= end_jd
                 and r["v:classification"] == "SN candidate"]
    assert 0 < len(discovery) < len(histories)
    transport = FinkReplay(discovery, histories)
    source = SN_QUERY + "with lightcurve via fink\nwith classification via fink\n"
    result = run_fink(source, transport, graph, now=SN_NOW)
    assert identities(result.portfolios) == {("ztf", r["i:objectId"]) for r in discovery}
    endpoint, params = transport.calls[0]
    assert endpoint == "latests" and params["class"] == "SN candidate"
    assert params["startdate"] == "2021-06-24T21:00:00.000000Z"
    assert params["stopdate"] == "2021-07-02T03:00:00.000000Z"
    assert result.run.steps[0].time_reference == SN_NOW
    # Compare unchanged raw object history to its own normalized measurements.
    # Keep all history, including measurements outside the discovery window.
    expected = {(r["i:candid"], r["i:jd"] - 2400000.5, r["i:magpsf"],
                 r["i:sigmapsf"], r["i:distnr"]) for r in histories}
    actual = set()
    for p in result.portfolios:
        for record in p.records_of_type("measurement@ztf:fink"):
            if record.internal_source.payload_key != "objects":
                continue
            raw = histories[record.internal_source.payload_index]
            band = {1: "g", 2: "r", 3: "i"}[raw["i:fid"]]
            actual.add((record.get("identity.source_id"), record.get("time.mjd"),
                        record.get(f"photometry.{band}.psf.mag"), record.get(f"photometry.{band}.psf.mag.error"),
                        record.get("reference_image.nearest_source.pixel_distance")))
            assert "reference_image.nearest_source.separation.total" not in record.fields
    assert actual == expected
    reported = {r.get("detection_count") for p in result.portfolios for r in p.records_of_type("summary@ztf:fink")}
    assert 17 in reported and len(histories) == 14  # Provider count and loaded history differ.


def test_discovery_filter_retrieve_binds_only_survivors_without_restricting_history(graph):
    rows = captured("fink/ztf/latests.json")
    transport = FinkReplay(rows)
    source = (IA_QUERY + "filter measurement@ztf:fink.position.ra > 30\n"
              "with lightcurve via fink\nwith classification via fink\n")
    result = run_fink(source, transport, graph)
    expected = {r["i:objectId"] for r in rows if r["i:ra"] > 30}
    assert 0 < len(expected) < len({r["i:objectId"] for r in rows})
    assert identities(result.portfolios) == {("ztf", oid) for oid in expected}
    object_calls = [p for endpoint, p in transport.calls if endpoint == "objects"]
    assert object_calls and all(set(p["objectId"].split(",")) == expected for p in object_calls)
    expected_candids = {r["i:candid"] for r in rows if r["i:objectId"] in expected}
    points = [point for p in result.portfolios for r in p.records_of_type("lightcurve@ztf:fink")
              for point in r.get("points", [])]
    assert {point["identity.source_id"] for point in points} == expected_candids


def test_multi_object_consumer_matches_each_objects_own_recorded_photometry_and_class(graph):
    # Different unchanged captures supply two different labels and magnitudes.
    rows = [captured("fink/ztf/objects_core.json")[0], captured("fink/ztf/latests.json")[0]]
    ids = [r["i:objectId"] for r in rows]
    assert len(set(ids)) == 2 and len({r["v:classification"] for r in rows}) == 2
    transport = FinkReplay([], rows)
    result = run_fink(f"objects {', '.join(ids)} from ztf via fink\nwith lightcurve via fink\n", transport, graph)
    assert identities(result.portfolios) == {("ztf", oid) for oid in ids}
    for raw in rows:
        p, = [p for p in result.portfolios if summary_object_identity(p) == ("ztf", raw["i:objectId"])]
        records = portfolio_to_dict(p)["records"]
        measurements = [r["fields"] for r in records if r["semantic_type"] == "measurement@ztf:fink"]
        band = {1: "g", 2: "r", 3: "i"}[raw["i:fid"]]
        assert {r["identity.source_id"] for r in measurements} == {raw["i:candid"]}
        assert {r[f"photometry.{band}.psf.mag"] for r in measurements} == {raw["i:magpsf"]}
        classes = [r["fields"] for r in records if r["semantic_type"] == "classification@fink"]
        assert {r["best.class"] for r in classes} == {raw["v:classification"]}


def test_empty_window_is_a_valid_empty_result_without_retrieval(graph):
    transport = FinkReplay([])
    result = run_fink(SN_QUERY + "with lightcurve via fink\n", transport, graph, now=SN_NOW)
    assert result.portfolios == ()
    assert [endpoint for endpoint, _ in transport.calls] == ["latests"]


@pytest.mark.parametrize("failure", ["saturated", "interrupted"])
def test_incomplete_window_cannot_become_success_or_empty(graph, failure):
    row = captured("fink/ztf/objects_core.json")[0]
    transport = FinkReplay([row] * 100, interrupted=failure == "interrupted")
    message = r"incomplete result.*n=100" if failure == "saturated" else "controlled interrupted discovery"
    with pytest.raises(WorkflowExecutionError, match=message):
        run_fink(SN_QUERY + "with lightcurve via fink\n", transport, graph, now=SN_NOW)
    assert [endpoint for endpoint, _ in transport.calls] == ["latests"]


# This table describes concrete requests, not blanket broker support. Geometry
# alone has existing cone routes even when semantic discovery needs a recipe.
@pytest.mark.parametrize("broker,origin,tail,runnable", [
    ("alerce", "ztf", "where summary.time.last_mjd >= 61000\n", True),
    ("alerce", "lsst", "where summary.time.last_mjd >= 61000\n", True),
    ("fink", "ztf", 'within 7d\nwhere classification.best.class = "SN candidate"\n', True),
    ("fink", "lsst", "", False),
    ("lasair", "ztf", "where summary.detection_count >= 5\n", True),
    ("lasair", "lsst", "", False),
    ("antares", "ztf", "where summary.position.ra >= 50 and summary.position.ra <= 52\n", True),
    ("antares", "lsst", "", False),
], ids=["alerce-ztf", "alerce-lsst", "fink-ztf", "fink-lsst", "lasair-ztf", "lasair-lsst", "antares-ztf", "antares-lsst"])
def test_provider_discovery_matrix_uses_public_validation(graph, broker, origin, tail, runnable):
    validation = validate_dsl(f"objects from {origin} via {broker}\n{tail}", graph=graph, continue_from=None)
    assert validation.is_valid
    assert validation.is_runnable is runnable, validation.lowering_error
    if not runnable:
        assert validation.lowering_error is not None and str(validation.lowering_error)


@pytest.mark.parametrize("broker", ["alerce", "fink", "lasair", "antares"])
@pytest.mark.parametrize("origin", ["ztf", "lsst"])
def test_provider_discovery_matrix_keeps_existing_unwindowed_cones(graph, broker, origin):
    source = f"objects from {origin} via {broker}\ninside (50.848, 37.468, 5arcsec)\n"
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error


@pytest.mark.parametrize("broker,origin,tail", [
    ("alerce", "lsst", "within 7d\n"),
    ("alerce", "lsst", "latest 1\n"),
    ("fink", "ztf", 'first within 7d\nwhere classification.best.class = "SN candidate"\n'),
    ("fink", "ztf", 'last within 7d\nwhere classification.best.class = "SN candidate"\n'),
    ("fink", "ztf", 'within 7d\nlatest 1\nwhere classification.best.class = "SN candidate"\n'),
    ("lasair", "ztf", 'where classification.best.class = "SN candidate"\n'),
    ("antares", "lsst", "where summary.position.ra >= 50\nwithin 7d\n"),
])
def test_provider_discovery_matrix_rejects_unproven_variants(graph, broker, origin, tail):
    validation = validate_dsl(f"objects from {origin} via {broker}\n{tail}", graph=graph, continue_from=None)
    assert validation.is_valid and not validation.is_runnable
    assert validation.lowering_error is not None


@pytest.mark.parametrize("broker", ["alerce", "lasair", "antares"])
@pytest.mark.parametrize("mode", ["", "first ", "last "])
def test_provider_discovery_matrix_admits_declared_ztf_time_and_latest_contracts(graph, broker, mode):
    condition = "where summary.position.ra >= 50 and summary.position.ra <= 52\n" if broker == "antares" else ""
    source = f"objects from ztf via {broker}\n{condition}{mode}within 7d\nlatest 1\n"
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
