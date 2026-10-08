"""Latest selects a complete semantic population, never one provider page."""

from itertools import count
from pathlib import Path
import shutil

import pytest
import yaml

from alertissimo.data_layer.execution import (
    EndpointRegistry, ExecutionPolicy, ExecutionPolicyLimitError, ExecutionResult,
    RegistryEndpointExecutor, TransportResult,
)
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.representations import (
    InternalExecutionId, InternalExecutionProvenance, InternalPortfolioId,
    InternalRecordId, Portfolio, SemanticRecord,
)
from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraphError, build_capability_graph,
)
from alertissimo.orchestration.binding import bind_endpoint
from alertissimo.orchestration.incremental import execute_incremental_workflow_run
from alertissimo.orchestration.ir import (
    ComparisonPredicate, ConeSearchStep, GetLightcurveStep, PredicateLiteral,
    SearchSelection, SemanticReference, SemanticSearchStep, Source, WorkflowIR,
)
from alertissimo.orchestration.normalization import (
    ExecutionPortfolioResult, SearchSelectionError, StepPortfolioResult,
    apply_search_selection, summary_object_identity,
)
from alertissimo.orchestration.pipeline import execute_staged_workflow_run
from alertissimo.orchestration.planner import PlanningDeferredError, plan_step, plan_workflow
from alertissimo.orchestration.runtime import WorkflowExecutionError
from alertissimo.orchestration.validation import validate_step_capabilities


def search(*, broker="alerce", origin="ztf", latest=1, **kwargs):
    return SemanticSearchStep(
        semantic_type="summary", sources=[Source(broker=broker, origin=origin)],
        selection=SearchSelection(latest=latest), **kwargs,
    )


def edit_yaml(path, update):
    document = yaml.safe_load(path.read_text())
    update(document)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def local_provider(tmp_path):
    root = tmp_path / "providers"
    destination = root / "alerce" / "ztf"
    shutil.copytree(PROVIDERS_ROOT / "alerce" / "ztf", destination)
    return root, destination


@pytest.mark.parametrize("cone", [False, True])
def test_latest_binds_verified_ordering_without_a_page_or_top_n_limit(cone):
    step = search(latest=7)
    if cone:
        step = ConeSearchStep(**step.model_dump(exclude={"op"}), ra=120, dec=-6, radius=30)
    graph = build_capability_graph()
    plan, = plan_step(step, graph)
    bound = bind_endpoint(step, plan, EndpointRegistry())
    assert bound.params == {
        **({"ra": 120, "dec": -6, "radius": 30} if cone else {}),
        "order_by": "lastmjd", "order_mode": "DESC",
    }
    assert graph.latest_selection_for("alerce", "lsst", "query_objects") is None
    assert plan_step(step.model_copy(update={"selection": None}), graph)[0].request_params == {}


@pytest.mark.parametrize("broker, origin", [("alerce", "lsst"), ("fink", "ztf"), ("lasair", "ztf"), ("antares", "ztf")])
def test_unproven_latest_contract_is_deferred(broker, origin):
    step = ConeSearchStep(
        semantic_type="summary", ra=120, dec=-6, radius=30,
        sources=[Source(broker=broker, origin=origin)], selection=SearchSelection(latest=1),
    )
    graph = build_capability_graph()
    assert validate_step_capabilities(step, graph).status == "deferred"
    with pytest.raises(PlanningDeferredError, match="latest requires"):
        plan_step(step, graph)


@pytest.mark.parametrize("change, message", [
    ("path", "latest requires summary.time.last_mjd"),
    ("mapping", "no endpoint mapping"),
    ("direction", "mapped raw ordering field and DESC"),
    ("ordering_field", "mapped raw ordering field and DESC"),
    ("pagination", "exhaustive page/page_size"),
    ("page_as_limit", "ordering server filters"),
    ("mode", "mapped JSON response mode"),
    ("assignment", "selection conflicts"),
])
def test_invalid_selection_claims_fail_at_loading(tmp_path, change, message):
    root, destination = local_provider(tmp_path)
    def capabilities(doc):
        selection = doc["selection_bindings"]["query_objects"]["latest"]
        if change == "path":
            selection["path"] = "summary.time.first_mjd"
        elif change == "direction":
            selection["params"]["order_mode"]["value"] = "ASC"
        elif change == "ordering_field":
            selection["params"]["order_by"]["value"] = "firstmjd"
        elif change == "page_as_limit":
            selection["params"]["page_size"] = {"from": "step.selection.latest"}
        elif change == "assignment":
            doc["recipes"]["cone_search"][0]["calls"][0]["params"]["order_by"] = {"value": "firstmjd"}
    edit_yaml(destination / "capabilities.yaml", capabilities)
    if change == "mapping":
        def mappings(doc):
            doc["mappings"]["summary@ztf:alerce.time.last_mjd"].remove("query_objects#lastmjd")
        edit_yaml(destination / "mappings.yaml", mappings)
    if change in {"pagination", "mode"}:
        def endpoints(doc):
            parameters = doc["endpoints"]["query_objects"]["params"]
            if change == "pagination":
                parameters["page"].pop("role")
            else:
                parameters["format"]["default"] = "pandas"
        edit_yaml(destination / "endpoints.yaml", endpoints)
    with pytest.raises(CapabilityGraphError, match=message):
        build_capability_graph(root)


def test_recipe_cannot_narrow_latest_to_one_explicit_page(tmp_path):
    root, destination = local_provider(tmp_path)
    def single_page(doc):
        doc["recipes"]["cone_search"][0]["calls"][0]["params"]["page"] = {"value": 1}
    edit_yaml(destination / "capabilities.yaml", single_page)
    step = ConeSearchStep(**search().model_dump(exclude={"op"}), ra=120, dec=-6, radius=30)
    assert validate_step_capabilities(step, build_capability_graph(root)).status == "deferred"


def test_selection_uses_authored_physical_parameter_names(tmp_path):
    root, destination = local_provider(tmp_path)
    renames = {"order_by": "sort_field", "order_mode": "sort_direction"}
    def endpoints(doc):
        endpoint = doc["endpoints"]["query_objects"]
        for old, new in renames.items():
            endpoint["params"][new] = endpoint["params"].pop(old)
        endpoint["server_filters"] = [renames.get(name, name) for name in endpoint["server_filters"]]
    def capabilities(doc):
        params = doc["selection_bindings"]["query_objects"]["latest"]["params"]
        for old, new in renames.items():
            params[new] = params.pop(old)
    edit_yaml(destination / "endpoints.yaml", endpoints)
    edit_yaml(destination / "capabilities.yaml", capabilities)
    step = search()
    plan, = plan_step(step, build_capability_graph(root))
    assert bind_endpoint(step, plan, EndpointRegistry(root)).params == {"sort_field": "lastmjd", "sort_direction": "DESC"}


@pytest.mark.parametrize("kind", ["field", "producer", "criteria"])
def test_latest_defers_unmaterialized_predicates_and_untranslated_criteria(kind):
    kwargs = {"criteria": {"limit": 1}} if kind == "criteria" else {"predicate": ComparisonPredicate(
        left=SemanticReference(
            semantic_type="classification" if kind == "producer" else "summary",
            field_path="best.class" if kind == "producer" else "missing",
            producer="lc_classifier" if kind == "producer" else None,
        ),
        operator="=", right=PredicateLiteral(value="SN"),
    )}
    assert validate_step_capabilities(search(**kwargs), build_capability_graph()).status == "deferred"


def portfolio(name, object_id, mjd, *, broker="a"):
    return Portfolio(
        internal_portfolio_id=InternalPortfolioId(name),
        records=(SemanticRecord(
            internal_record_id=InternalRecordId(f"record:{name}"),
            semantic_type=f"summary@ztf:{broker}",
            fields={"identity.object_id": object_id, "time.last_mjd": mjd},
        ),),
    )


def test_latest_is_global_after_cross_source_consolidation_with_stable_ties():
    executions = (
        ExecutionPortfolioResult("a", (portfolio("a1", "A", 80), portfolio("a2", "B", 100))),
        ExecutionPortfolioResult("b", (portfolio("b1", "A", 110, broker="b"), portfolio("b2", "C", 100, broker="b"))),
    )
    selected = apply_search_selection(search(latest=2), StepPortfolioResult(0, executions))
    assert [summary_object_identity(item)[1] for item in selected.portfolios] == ["A", "B"]
    assert len(selected.portfolios[0].records) == 2
    assert selected.executions == executions
    assert apply_search_selection(search(), StepPortfolioResult(0, ())).portfolios == ()


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), "60000", True])
def test_latest_rejects_missing_or_invalid_recency_values(value):
    view = StepPortfolioResult(0, (ExecutionPortfolioResult("bad", (portfolio("bad", "A", value),)),))
    with pytest.raises(SearchSelectionError):
        apply_search_selection(search(), view)


class FixtureExecutor:
    def __init__(self):
        self.calls = []
        self.ids = count(1)

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        self.calls.append((broker, origin, endpoint, dict(params or {})))
        payload = {"items": [
            {"oid": "A", "lastmjd": 120, "ndet": 1},
            {"oid": "B", "lastmjd": 110, "ndet": 5},
            {"oid": "B", "lastmjd": 110, "ndet": 5},
            {"oid": "C", "lastmjd": 100, "ndet": 5},
        ]} if broker == "alerce" else []
        return ExecutionResult(payload=payload, execution_provenance=InternalExecutionProvenance(
            internal_execution_id=InternalExecutionId(f"selection:{next(self.ids)}"),
            broker=broker, origin=origin, endpoint=endpoint, params=dict(params or {}),
        ))


def test_residual_then_latest_feeds_selected_ids_and_survives_continuation():
    graph, registry, executor = build_capability_graph(), EndpointRegistry(), FixtureExecutor()
    step = search(predicate=ComparisonPredicate(
        left=SemanticReference(semantic_type="summary", field_path="detection_count"),
        operator=">=", right=PredicateLiteral(value=3),
    ))
    first_workflow = WorkflowIR(steps=[step])
    first = execute_staged_workflow_run(plan_workflow(first_workflow, graph), registry, executor)
    assert [summary_object_identity(item)[1] for item in first.normalized.steps[0].portfolios] == ["B"]
    assert {summary_object_identity(item)[1] for item in first.normalized.steps[0].executions[0].portfolios} == {"B", "C"}
    extended = WorkflowIR(steps=[step, GetLightcurveStep(sources=[Source(broker="fink", origin="ztf")])])
    continued = execute_incremental_workflow_run(plan_workflow(extended, graph), first, registry, executor)
    assert [call[0] for call in executor.calls] == ["alerce", "fink"]
    assert executor.calls[-1][3]["objectId"] == "B"
    assert [summary_object_identity(item)[1] for item in continued.normalized.steps[0].portfolios] == ["B"]
    assert [summary_object_identity(item)[1] for item in continued.normalized.steps[1].portfolios] == ["B"]


class PageTransport:
    name = "fixture"

    def __init__(self):
        self.calls = []

    def execute(self, spec, params, headers=None):
        self.calls.append(dict(params))
        pages = {
            1: [{"oid": "A", "lastmjd": 80}, {"oid": "A", "lastmjd": 80}],
            2: [{"oid": "B", "lastmjd": 90}, {"oid": "C", "lastmjd": 100}],
            3: [{"oid": "D", "lastmjd": 110}],
        }
        page = params.get("page", 1)
        return TransportResult({
            "items": pages[page], "page": page,
            "has_next": page < 3, "next": page + 1 if page < 3 else None,
        })


@pytest.mark.parametrize("max_pages", [1, 3])
def test_pagination_is_exhaustive_and_policy_exhaustion_cannot_return_false_latest(max_pages):
    graph, registry, transport = build_capability_graph(), EndpointRegistry(), PageTransport()
    executor = RegistryEndpointExecutor(
        registry, transports={"python_client": transport},
        policy=ExecutionPolicy(2, max_pages, Path("selection-fixture")),
        execution_id_factory=lambda: InternalExecutionId("selection:paged"),
    )
    run = plan_workflow(WorkflowIR(steps=[search()]), graph)
    if max_pages == 1:
        with pytest.raises(WorkflowExecutionError) as error:
            execute_staged_workflow_run(run, registry, executor)
        assert isinstance(error.value.__cause__, ExecutionPolicyLimitError)
    else:
        result = execute_staged_workflow_run(run, registry, executor)
        assert [summary_object_identity(item)[1] for item in result.normalized.steps[0].portfolios] == ["D"]
        assert len(transport.calls) == 3
        assert all(item["page_size"] == 2 and item["order_by"] == "lastmjd" for item in transport.calls)
