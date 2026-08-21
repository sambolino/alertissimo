"""End-to-end local MatchStep flow from literal DSL through normalized Portfolios."""

from itertools import count

from alertissimo.data_layer.execution import EndpointRegistry, ExecutionResult
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import compile_surface_to_ir, parse_surface_script
from alertissimo.orchestration.ir import MatchStep
from alertissimo.orchestration.local_semantics import finalize_local_semantics
from alertissimo.orchestration.pipeline import execute_staged_workflow_run
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.runtime import StepRunState


DSL = """objects from lsst, ztf via alerce
inside (10, 20, 5arcsec)
match on position inside 1arcsec
"""

SINGLE_SURVEY_DSL = """objects from lsst via alerce
inside (10, 20, 5arcsec)
match on position inside 1arcsec
"""


class _MultisurveyMatchExecutor:
    """Return minimal authoritative ALeRCE-shaped search rows without network I/O."""

    def __init__(self):
        self.calls: list[tuple[str, str, str, dict]] = []
        self._ids = count(1)

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        del headers
        params = dict(params or {})
        self.calls.append((broker, origin, endpoint, params))
        assert broker == "alerce"
        assert endpoint == "query_objects"

        if origin == "lsst":
            payload = [
                {
                    "oid": 170000000000000001,
                    "meanra": 10.0,
                    "meandec": 20.0,
                }
            ]
        elif origin == "ztf":
            payload = {
                "items": [
                    {
                        "oid": "ZTF20match",
                        "meanra": 10.0001,
                        "meandec": 20.0,
                    }
                ]
            }
        else:  # pragma: no cover - planner contract below fixes the two origins.
            raise AssertionError(f"unexpected origin {origin!r}")

        execution_id = InternalExecutionId(f"execution:match:{next(self._ids)}")
        return ExecutionResult(
            payload=payload,
            execution_provenance=InternalExecutionProvenance(
                internal_execution_id=execution_id,
                broker=broker,
                origin=origin,
                endpoint=endpoint,
                params=params,
            ),
        )


class _SingleSurveyMatchExecutor:
    """Return two distinct nearby LSST object identities from one search execution."""

    def __init__(self):
        self.calls: list[tuple[str, str, str, dict]] = []

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        del headers
        params = dict(params or {})
        self.calls.append((broker, origin, endpoint, params))
        assert (broker, origin, endpoint) == ("alerce", "lsst", "query_objects")
        return ExecutionResult(
            payload=[
                {
                    "oid": 170000000000000001,
                    "meanra": 10.0,
                    "meandec": 20.0,
                },
                {
                    "oid": 170000000000000002,
                    "meanra": 10.00001,
                    "meandec": 20.0,
                },
            ],
            execution_provenance=InternalExecutionProvenance(
                internal_execution_id=InternalExecutionId("execution:match:lsst"),
                broker=broker,
                origin=origin,
                endpoint=endpoint,
                params=params,
            ),
        )


def test_literal_multisurvey_dsl_executes_search_then_local_cross_survey_match():
    graph = build_capability_graph()
    workflow = compile_surface_to_ir(
        parse_surface_script(DSL),
        graph=graph,
        name="offline LSST-ZTF MatchStep acceptance",
    )

    assert len(workflow.steps) == 2
    search, match = workflow.steps
    assert search.op == "cone_search"
    assert isinstance(match, MatchStep)
    assert match.method is None
    assert match.params == {
        "candidate_origins": ["lsst", "ztf"],
        "predicate": "position inside 1arcsec",
    }

    run = plan_workflow(workflow, graph)
    assert {
        (plan.broker, plan.origin, plan.endpoint)
        for plan in run.steps[0].endpoint_plans
    } == {
        ("alerce", "lsst", "query_objects"),
        ("alerce", "ztf", "query_objects"),
    }
    assert run.steps[1].endpoint_plans == ()
    assert run.steps[1].candidate_input_from is not None
    assert run.steps[1].candidate_input_from.step_index == 0

    executor = _MultisurveyMatchExecutor()
    staged = execute_staged_workflow_run(
        run,
        EndpointRegistry(),
        executor,
        validate_semantic_model=True,
    )

    # Only Search owns physical work. Match is explicitly deferred to the local
    # post-normalization semantic phase and fabricates no execution provenance.
    assert len(executor.calls) == 2
    assert {call[1] for call in executor.calls} == {"lsst", "ztf"}
    assert staged.run.steps[0].state is StepRunState.SUCCEEDED
    assert staged.run.steps[1].state is StepRunState.PLANNED
    assert staged.bindings[1].bound_calls == ()
    assert staged.execution.steps[1].executions == ()
    assert staged.normalized.steps[1].executions == ()

    search_view = staged.normalized.steps[0]
    assert len(search_view.portfolios) == 2
    positions = {
        record.semantic_type.split("@", 1)[1].split(":", 1)[0]: (
            record.fields.get("position.ra"),
            record.fields.get("position.dec"),
        )
        for portfolio in search_view.portfolios
        for record in portfolio.records
        if record.semantic_type.startswith("summary@")
    }
    assert positions == {
        "lsst": (10.0, 20.0),
        "ztf": (10.0001, 20.0),
    }
    assert all(not portfolio.edges for portfolio in search_view.portfolios)

    finalized = finalize_local_semantics(staged.normalized)
    assert finalized.run.steps[1].state is StepRunState.SUCCEEDED
    assert finalized.run.steps[1].execution_ids == ()

    # Historical Search output is untouched; the Match occurrence owns the
    # adjacency-annotated semantic view.
    assert all(not portfolio.edges for portfolio in finalized.steps[0].portfolios)
    match_view = finalized.steps[1]
    assert match_view.step_index == 1
    assert len(match_view.portfolios) == 2
    left, right = match_view.portfolios
    assert len(left.edges) == len(right.edges) == 1
    assert left.edges[0].internal_edge_id == right.edges[0].internal_edge_id
    assert left.edges[0].edge_type == right.edges[0].edge_type == "--spatially_near--"
    assert left.edges[0].fields["angular_separation"] < 1.0
    assert {
        execution.origin
        for portfolio in match_view.portfolios
        for execution in portfolio.executions
    } == {"lsst", "ztf"}


def test_literal_single_survey_dsl_can_match_distinct_object_ids_locally():
    graph = build_capability_graph()
    workflow = compile_surface_to_ir(
        parse_surface_script(SINGLE_SURVEY_DSL),
        graph=graph,
        name="offline same-survey MatchStep acceptance",
    )

    assert len(workflow.steps) == 2
    search, match = workflow.steps
    assert search.op == "cone_search"
    assert isinstance(match, MatchStep)
    assert match.params == {
        "candidate_origins": ["lsst"],
        "predicate": "position inside 1arcsec",
    }

    run = plan_workflow(workflow, graph)
    assert {
        (plan.broker, plan.origin, plan.endpoint)
        for plan in run.steps[0].endpoint_plans
    } == {("alerce", "lsst", "query_objects")}
    assert run.steps[1].endpoint_plans == ()
    assert run.steps[1].candidate_input_from is not None
    assert run.steps[1].candidate_input_from.step_index == 0

    executor = _SingleSurveyMatchExecutor()
    staged = execute_staged_workflow_run(
        run,
        EndpointRegistry(),
        executor,
        validate_semantic_model=True,
    )

    assert len(executor.calls) == 1
    assert staged.run.steps[0].state is StepRunState.SUCCEEDED
    assert staged.run.steps[1].state is StepRunState.PLANNED
    assert staged.bindings[1].bound_calls == ()
    assert staged.execution.steps[1].executions == ()

    search_view = staged.normalized.steps[0]
    assert len(search_view.portfolios) == 2
    assert all(not portfolio.edges for portfolio in search_view.portfolios)

    finalized = finalize_local_semantics(staged.normalized)
    assert finalized.run.steps[1].state is StepRunState.SUCCEEDED
    assert finalized.run.steps[1].execution_ids == ()
    assert all(not portfolio.edges for portfolio in finalized.steps[0].portfolios)

    match_view = finalized.steps[1]
    assert len(match_view.portfolios) == 2
    left, right = match_view.portfolios
    assert len(left.edges) == len(right.edges) == 1
    assert left.edges[0].internal_edge_id == right.edges[0].internal_edge_id
    assert left.edges[0].edge_type == right.edges[0].edge_type == "--spatially_near--"
    assert left.edges[0].target == right.internal_portfolio_id
    assert right.edges[0].target == left.internal_portfolio_id
    assert left.edges[0].fields["angular_separation"] < 1.0
    assert {
        execution.origin
        for portfolio in match_view.portfolios
        for execution in portfolio.executions
    } == {"lsst"}
