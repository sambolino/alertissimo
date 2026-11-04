"""Latest ranks initial evidence survivors by frozen, completely paged discovery.

Synthetic transports exercise production registry execution without provider calls.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import (
    ExecutionPolicy, ExecutionPolicyLimitError, RegistryEndpointExecutor, TransportResult,
)
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import SurfaceLoweringError
from alertissimo.orchestration.ir import (
    FilterStep, GetClassificationStep, SearchSelection, TargetSelector, WorkflowIR,
)
from alertissimo.orchestration.normalization import SearchSelectionError, normalize_workflow_execution, summary_object_identity
from alertissimo.orchestration.planner import PlanningDeferredError, plan_workflow
from alertissimo.orchestration.runtime import WorkflowExecutionError, WorkflowRun


IDS = tuple(f"ZTF20{letter * 7}" for letter in "abcd")
NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)
CONE = "objects from ztf via alerce\ninside (124.88, -6.02, 5arcsec)\n"
CONDITION = 'classification@fink:fink.best.class = "SN candidate"'


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def identities(portfolios):
    return [summary_object_identity(portfolio)[1] for portfolio in portfolios]


def program(count=2, tail=None):
    return CONE + f"latest {count}\n" + (tail or 'with classification via fink where best.class = "SN candidate"\n')


class ReplayTransport:
    def __init__(self, *, labels=None, recencies=(61004, 61003, 61002, 61002), empty=False,
                 missing_recency=False, fail_classification=False, omit_summary=False):
        self.calls = []
        self.labels = labels if labels is not None else {IDS[0]: "AGN", **dict.fromkeys(IDS[1:], "SN candidate")}
        self.rows = [
            {"oid": oid, "meanra": 124.88, "meandec": -6.02,
             "firstmjd": 58000, "lastmjd": date, "ndet": 10 * index}
            for index, (oid, date) in enumerate(zip(IDS, recencies))
        ]
        # A repeated object across pages must not consume a latest slot.
        self.rows.insert(2, deepcopy(self.rows[1]))
        if empty:
            self.rows = []
        if missing_recency:
            for row in self.rows:
                if row["oid"] == IDS[1]:
                    row.pop("lastmjd")
        self.fail_classification = fail_classification
        self.omit_summary = omit_summary

    def execute(self, spec, params, headers=None):
        params = dict(params)
        self.calls.append((spec.broker, spec.endpoint, deepcopy(params)))
        if spec.broker == "lasair":
            assert headers["Authorization"] == "Token fixture-only"
            unique = {row["oid"]: row for row in self.rows}
            if spec.endpoint == "cone":
                assert params["requestType"] == "all"
                return TransportResult([{"object": oid, "separation": 1.0} for oid in unique])
            assert spec.endpoint == "query"
            assert all(oid in params["conditions"] for oid in unique)
            return TransportResult([
                {"objectId": oid, "ramean": row["meanra"], "decmean": row["meandec"],
                 "ncand": row["ndet"], "jdmin": row["firstmjd"] + 2400000.5,
                 "jdmax": row["lastmjd"] + 2400000.5}
                for oid, row in unique.items() if not self.omit_summary or oid != IDS[2]
            ])
        if spec.broker == "alerce":
            assert spec.endpoint == "query_objects" and params["survey"] == "ztf"
            assert params["order_by"] == "lastmjd" and params["order_mode"] == "DESC"
            assert "count" not in params
            page, size = params.get("page", 1), params["page_size"]
            more = page * size < len(self.rows)
            return TransportResult({"items": deepcopy(self.rows[(page - 1) * size:page * size]),
                                    "page": page, "has_next": more,
                                    "next": page + 1 if more else None})
        assert (spec.broker, spec.endpoint) == ("fink", "objects")
        if self.fail_classification:
            raise RuntimeError("classification unavailable")
        return TransportResult([
            {"i:objectId": oid, "i:candid": 1000 + IDS.index(oid) * 10 + point,
             "i:jd": 2461000.5 + point, "i:fid": 1, "i:magpsf": 19 + point / 10,
             "i:sigmapsf": 0.1, "i:ra": 124.88, "i:dec": -6.02, "i:ndethist": 2,
             # Enrichment would incorrectly promote C above B if used for recency.
             "i:jdendhist": 2400000.5 + (62000 if oid == IDS[2] else 61000),
             **({"v:classification": self.labels[oid]} if oid in self.labels else {})}
            for oid in params["objectId"].split(",") for point in range(2)
        ])


def executor(transport, max_pages=8):
    return RegistryEndpointExecutor(
        transports={"python_client": transport, "rest": transport},
        policy=ExecutionPolicy(2, max_pages, Path("latest-evidence-fixture")),
    )


@pytest.mark.parametrize("tail", [
    'with classification via fink where best.class = "SN candidate"\n',
    f"where {CONDITION}\n",
    f"with classification via fink\nwhere {CONDITION}\n",
])
def test_latest_waits_for_initial_predicate_and_uses_only_discovery_recency(graph, tail):
    source = program(tail=tail)
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    transport = ReplayTransport()
    result = execute_dsl(source, graph=graph, executor=executor(transport), continue_from=None)
    assert [step.op for step in result.workflow.steps] == ["cone_search", "get_classification", "filter"]
    assert result.workflow.steps[0].selection == SearchSelection(latest=2, after_step=2)
    assert result.workflow.steps[0].predicate is None
    assert identities(result.result.steps[0].portfolios) == list(IDS)
    assert identities(result.result.steps[1].portfolios) == list(IDS)
    assert identities(result.portfolios) == list(IDS[1:3])
    assert [name for _, name, _ in transport.calls] == ["query_objects"] * 3 + ["objects"]
    assert transport.calls[-1][2]["objectId"] == ",".join(IDS)
    assert sum(record.semantic_type == "measurement@ztf:fink"
               for portfolio in result.portfolios for record in portfolio.records) == 4
    enriched = {summary_object_identity(p)[1]: max(r.get("time.last_mjd") for r in p.records
                if r.semantic_type.startswith("summary@ztf:") and r.get("time.last_mjd") is not None)
                for p in result.result.steps[1].portfolios}
    assert max(enriched, key=enriched.get) == IDS[2]
    assert identities(normalize_workflow_execution(result.staged.execution).steps[2].portfolios) == list(IDS[1:3])
    assert WorkflowIR.model_validate_json(result.workflow.model_dump_json()) == result.workflow
    assert WorkflowRun.model_validate_json(result.run.model_dump_json()) == result.run


def test_latest_boundary_precedes_explicit_filter_and_downstream_retrieval(graph):
    source = program() + "filter summary@ztf:alerce.detection_count >= 20\nwith lightcurve via fink\n"
    transport = ReplayTransport()
    result = execute_dsl(source, graph=graph, executor=executor(transport), continue_from=None)
    assert result.workflow.steps[0].selection.after_step == 2
    assert identities(result.result.steps[2].portfolios) == list(IDS[1:3])
    assert identities(result.portfolios) == [IDS[2]]
    assert transport.calls[-1][2]["objectId"] == IDS[2]


@pytest.mark.parametrize("omit_summary", [False, True])
def test_composite_cone_retains_required_recency_coverage_before_external_evidence(graph, monkeypatch, omit_summary):
    monkeypatch.setenv("LASAIR_ZTF_TOKEN", "fixture-only")
    transport = ReplayTransport(omit_summary=omit_summary)
    source = program().replace("via alerce", "via lasair")
    if omit_summary:
        with pytest.raises(SearchSelectionError, match="latest summary does not cover exactly"):
            execute_dsl(source, graph=graph, executor=executor(transport), continue_from=None)
        assert [name for _, name, _ in transport.calls] == ["cone", "query"]
        return
    result = execute_dsl(source, graph=graph, executor=executor(transport), continue_from=None)
    owner, summary = result.run.steps[0].endpoint_plans
    assert owner.required and summary.required
    assert owner.latest_selection.evidence_plan_index == 1
    assert result.workflow.steps[0].selection.after_step == 2
    assert identities(result.result.steps[0].portfolios) == list(IDS)
    assert identities(result.portfolios) == list(IDS[1:3])
    assert [name for _, name, _ in transport.calls] == ["cone", "query", "objects"]


def test_continuation_replays_old_population_and_never_refills_latest(graph):
    transport = ReplayTransport()
    endpoint_executor = executor(transport)
    first = execute_dsl(program(count=1), graph=graph, executor=endpoint_executor,
                        continue_from=None, reference_time=NOW)
    snapshot = first.to_dict()
    second = execute_dsl("with lightcurve via fink\n", graph=graph, executor=endpoint_executor,
                         continue_from=first, reference_time=NOW + timedelta(days=1))
    assert identities(first.portfolios) == identities(second.portfolios) == [IDS[1]]
    assert transport.calls[-1][2]["objectId"] == IDS[1]
    assert len(transport.calls) == 5
    old_calls = deepcopy(transport.calls)
    third = execute_dsl("filter summary@ztf:alerce.detection_count >= 20\nwith lightcurve via fink\n",
                        graph=graph, executor=endpoint_executor, continue_from=second,
                        reference_time=NOW + timedelta(days=2))
    assert third.portfolios == ()
    assert transport.calls == old_calls
    assert first.to_dict() == snapshot
    assert second.workflow.steps[:len(first.workflow.steps)] == first.workflow.steps
    assert third.workflow.steps[:len(second.workflow.steps)] == second.workflow.steps


@pytest.mark.parametrize("empty_discovery", [False, True])
def test_empty_initial_population_does_not_fetch_downstream_or_invent_a_match(graph, empty_discovery):
    transport = ReplayTransport(labels={}, empty=empty_discovery)
    result = execute_dsl(program() + "filter exists summary.identity.object_id\nwith lightcurve via fink\n",
                         graph=graph, executor=executor(transport), continue_from=None)
    assert result.portfolios == ()
    assert [name for _, name, _ in transport.calls] == (["query_objects"] if empty_discovery
                                                      else ["query_objects"] * 3 + ["objects"])


def test_tied_recency_uses_identity_after_evidence_pruning(graph):
    transport = ReplayTransport(recencies=(61004, 61002, 61002, 61002))
    result = execute_dsl(program(count=1), graph=graph, executor=executor(transport), continue_from=None)
    assert identities(result.portfolios) == [IDS[1]]


@pytest.mark.parametrize("broken", ["paging", "classification", "recency"])
def test_partial_or_missing_required_evidence_never_becomes_a_latest_success(graph, broken):
    transport = ReplayTransport(missing_recency=broken == "recency", fail_classification=broken == "classification")
    with pytest.raises(WorkflowExecutionError) as error:
        execute_dsl(program(), graph=graph, executor=executor(transport, max_pages=1 if broken == "paging" else 8),
                    continue_from=None)
    if broken == "paging":
        assert isinstance(error.value.__cause__, ExecutionPolicyLimitError)
        assert len(transport.calls) == 1


@pytest.mark.parametrize("prefix", [CONE.replace("via alerce", "via fink"), CONE.replace("from ztf", "from lsst")])
def test_unproven_discovery_latest_contract_still_defers_before_transport(graph, prefix):
    source = prefix + 'latest 1\nwith classification via lasair where best.class = "SN"\n'
    assert not validate_dsl(source, graph=graph, continue_from=None).is_runnable
    transport = ReplayTransport()
    with pytest.raises((SurfaceLoweringError, PlanningDeferredError)):
        execute_dsl(source, graph=graph, executor=executor(transport), continue_from=None)
    assert transport.calls == []


@pytest.mark.parametrize("change", ["past", "unknown", "not_filter", "explicit_target", "cross_filter"])
def test_invalid_latest_boundaries_fail_before_endpoint_planning(graph, change):
    validation = validate_dsl(program(), graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    workflow = validation.compilation.workflow.model_copy(deep=True)
    steps = list(workflow.steps)
    boundary = 2
    if change == "past":
        boundary = 0
    elif change == "unknown":
        boundary = 99
    elif change == "not_filter":
        boundary = 1
    elif change == "explicit_target":
        steps[1] = GetClassificationStep(target=TargetSelector(ids=[IDS[1]], kind="object"))
    else:
        steps.insert(1, FilterStep(predicate=steps[2].predicate))
        boundary = 3
    steps[0] = steps[0].model_copy(update={"selection": SearchSelection(latest=2, after_step=boundary)})
    with pytest.raises(ValidationError, match="latest after_step"):
        plan_workflow(WorkflowIR(steps=steps), graph)
