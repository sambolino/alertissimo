"""ZTF numeric discovery through real declarations and a fake native client.

No HTTP requests or installed ANTARES package are used. Frozen listing rows are
reused unchanged where indicated; extra candidates and pages are synthetic.
"""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest
import yaml

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.runtime.capability_graph import CapabilityGraphError, build_capability_graph
from alertissimo.orchestration.binding import bind_endpoint
from alertissimo.orchestration.ir import (
    BooleanPredicate, ComparisonPredicate, PredicateLiteral,
    SemanticReference, SemanticSearchStep, Source,
)
from alertissimo.orchestration.normalization import normalize_workflow_execution, summary_object_identity
from alertissimo.orchestration.planner import PlanningDeferredError, plan_step
from alertissimo.orchestration.runtime import WorkflowExecutionError


FIXTURES = Path(__file__).parent / "fixtures/antares/ztf"
FROZEN = json.loads((FIXTURES / "search.json").read_text())[0]
CANDIDATE = next(a for a in json.loads((FIXTURES / "alerts.json").read_text())
                 if a["properties"].get("ant_mag") is not None)
IDS = (FROZEN["properties"]["ztf_object_id"], "ZTF20bbbbbbb")


def rows():
    a = deepcopy(FROZEN)
    b = {**deepcopy(FROZEN), "locus_id": "ANT-B", "ra": 51.0}
    b["properties"]["ztf_object_id"] = IDS[1]
    return [a, b]


def identities(portfolios):
    return {summary_object_identity(p)[1] for p in portfolios}


class NativeClient:
    def __init__(self, pages=None, fail=False):
        self.pages = [[row] for row in rows()] if pages is None else pages
        self.fail = fail
        self.calls = []
        self.pages_read = 0

    def search(self, query):
        self.calls.append(("search", deepcopy(query)))
        for page in self.pages:
            self.pages_read += 1
            yield from deepcopy(page)
            if self.fail:
                raise RuntimeError("controlled later-page failure")

    def get_by_ztf_object_id(self, ztf_object_id):
        self.calls.append(("get_by_ztf_object_id", ztf_object_id))
        row = next(row for row in rows() if row["properties"]["ztf_object_id"] == ztf_object_id)
        alert = deepcopy(CANDIDATE)
        alert["properties"]["ztf_object_id"] = ztf_object_id
        return {**row, "alerts": [alert], "catalog_objects": {}}


def executor(monkeypatch, client):
    monkeypatch.setitem(sys.modules, "antares_client.search", SimpleNamespace(
        search=client.search, get_by_ztf_object_id=client.get_by_ztf_object_id,
    ))
    return RegistryEndpointExecutor()


def source(tail=""):
    return ("objects from ztf via antares\n"
            "where summary.position.ra >= 50 and summary.position.ra <= 52\n" + tail)


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def test_scoped_coordinates_plan_bind_and_recheck_index_identity(graph):
    validation = validate_dsl(source(), graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    step, = validation.compilation.workflow.steps
    assert step.op == "semantic_search"
    plan, = plan_step(step, graph)
    assert plan.endpoint == "search" and plan.execution_reuse_from is None
    bound = bind_endpoint(step, plan, EndpointRegistry())
    assert bound.params == {"query": {"query": {"bool": {"filter": [
        {"bool": {"filter": [{"exists": {"field": "properties.ztf_object_id"}}, {"range": {"ra": {"gte": 50}}}]}},
        {"bool": {"filter": [{"exists": {"field": "properties.ztf_object_id"}}, {"range": {"ra": {"lte": 52}}}]}},
    ]}}}}
    assert plan.predicate_realization.residual is not None
    assert graph.query_recipes(broker="antares", origin="lsst", op="semantic_search") == ()


def test_frozen_and_synthetic_pages_are_replayable_and_survivors_bind_retrieval(graph, monkeypatch):
    client = NativeClient()
    endpoint_executor = executor(monkeypatch, client)
    first = execute_dsl(source(), graph=graph, executor=endpoint_executor, continue_from=None)
    assert identities(first.portfolios) == set(IDS)
    assert client.pages_read == 2 and len(client.calls) == 1
    assert isinstance(first.staged.execution.steps[0].executions[0].payload, tuple)
    assert first.staged.execution.steps[0].executions[0].payload[0] == FROZEN
    assert identities(normalize_workflow_execution(first.staged.execution).steps[0].portfolios) == set(IDS)
    second = execute_dsl("filter summary.position.ra >= 51\nwith lightcurve via antares\n",
                         graph=graph, executor=endpoint_executor, continue_from=first)
    assert client.calls[1:] == [("get_by_ztf_object_id", IDS[1])]
    assert client.pages_read == 2
    assert identities(second.portfolios) == {IDS[1]}
    assert identities(first.portfolios) == set(IDS)
    assert second.run.steps[0].execution_ids == first.run.steps[0].execution_ids
    assert any(r.semantic_type == "detection@ztf:antares" for r in second.portfolios[0].records)
    assert identities(normalize_workflow_execution(second.staged.execution).steps[-1].portfolios) == {IDS[1]}


def test_overbroad_response_cannot_promote_foreign_identity_or_outside_coordinates(graph, monkeypatch):
    outside = {**deepcopy(FROZEN), "locus_id": "ANT-outside", "ra": 49.0}
    outside["properties"]["ztf_object_id"] = "ZTF20ccccccc"
    foreign = {**deepcopy(FROZEN), "locus_id": "ANT-LSST"}
    foreign["properties"] = {"lsst_dia_object_id": "123"}
    client = NativeClient(pages=[rows() + [outside, foreign]])
    result = execute_dsl(source(tail="with lightcurve via antares\n"), graph=graph,
                         executor=executor(monkeypatch, client), continue_from=None)
    assert identities(result.portfolios) == set(IDS)
    assert [name for name, _ in client.calls] == ["search", "get_by_ztf_object_id", "get_by_ztf_object_id"]
    assert {value for _, value in client.calls[1:]} == set(IDS)


def test_empty_search_does_not_issue_targeted_retrieval(graph, monkeypatch):
    client = NativeClient(pages=[])
    result = execute_dsl(source(tail="with lightcurve via antares\n"), graph=graph,
                         executor=executor(monkeypatch, client), continue_from=None)
    assert result.portfolios == () and len(client.calls) == 1


def test_iterator_failure_is_owned_by_execution_and_cannot_become_partial_success(graph, monkeypatch):
    client = NativeClient(fail=True)
    with pytest.raises(WorkflowExecutionError, match="controlled later-page failure"):
        execute_dsl(source(tail="with lightcurve via antares\n"), graph=graph,
                    executor=executor(monkeypatch, client), continue_from=None)
    assert [name for name, _ in client.calls] == ["search"]


@pytest.mark.parametrize("predicate", [
    None,
    ComparisonPredicate(left=SemanticReference(semantic_type="summary", field_path="position.ra"),
                        operator=">=", right=PredicateLiteral(value="50")),
    ComparisonPredicate(left=SemanticReference(semantic_type="summary", field_path="position.ra", channel="fink"),
                        operator=">=", right=PredicateLiteral(value=50)),
    BooleanPredicate(operator="or", operands=(
        ComparisonPredicate(left=SemanticReference(semantic_type="summary", field_path="position.ra"),
                            operator=">=", right=PredicateLiteral(value=50)),
        ComparisonPredicate(left=SemanticReference(semantic_type="summary", field_path="position.dec"),
                            operator=">=", right=PredicateLiteral(value=37)),
    )),
])
def test_missing_or_untranslated_query_is_not_a_full_catalog_scan(graph, predicate):
    step = SemanticSearchStep(sources=[Source(broker="antares", origin="ztf")],
                              semantic_type="summary", predicate=predicate)
    with pytest.raises(PlanningDeferredError, match="eligible predicate assignment"):
        plan_step(step, graph)


def test_latest_requires_complete_histories_before_ranking(graph, monkeypatch):
    client = NativeClient()
    endpoint_executor = executor(monkeypatch, client)
    validation = validate_dsl(source("latest 1\n"), graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    result = execute_dsl(source("latest 1\n"), graph=graph, executor=endpoint_executor, continue_from=None)
    assert identities(result.portfolios) == {min(IDS)}  # equal detection dates: stable object-ID tie
    assert [name for name, _ in client.calls] == ["search", "get_by_ztf_object_id", "get_by_ztf_object_id"]
    assert {value for _, value in client.calls[1:]} == set(IDS)
    assert result.run.steps[0].endpoint_plans[0].latest_selection.history.complete


@pytest.mark.parametrize("identity", [None, "properties.missing", "properties.ztf_object_id;script"])
def test_identity_scope_must_be_a_mapped_identity(tmp_path, identity):
    root = tmp_path / "providers"
    destination = root / "antares/ztf"
    shutil.copytree(PROVIDERS_ROOT / "antares/ztf", destination)
    path = destination / "capabilities.yaml"
    document = yaml.safe_load(path.read_text())
    document["predicate_bindings"]["search"][0]["elasticsearch"]["identity_field"] = identity
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    with pytest.raises(CapabilityGraphError, match="identity field"):
        build_capability_graph(root)
