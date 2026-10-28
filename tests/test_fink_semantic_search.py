"""Fink ZTF class discovery uses the verified latests request contract."""

from datetime import datetime, timezone

import pytest

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import (
    EndpointRegistry,
    RegistryEndpointExecutor,
    TransportResult,
)
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import SurfaceLoweringError, lower_surface, parse_surface_script
from alertissimo.orchestration.binding import bind_endpoint
from alertissimo.orchestration.ir import SemanticSearchStep
from alertissimo.orchestration.planner import PlanningDeferredError, plan_step
from alertissimo.orchestration.validation import validate_step_capabilities


NOW = datetime(2026, 10, 28, 12, 34, 56, 123456, tzinfo=timezone.utc)
SEARCH = (
    "objects from ztf via fink\n"
    "within 7d\n"
    'where classification.best.class = "SN candidate"\n'
)


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def test_fink_class_and_time_window_validate_plan_and_bind(graph):
    validation = validate_dsl(SEARCH, graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error

    step = validation.compilation.workflow.steps[0]
    assert isinstance(step, SemanticSearchStep)
    plan, = plan_step(step, graph)
    assert plan.endpoint == "latests"
    assert plan.predicate_realization.params == {"class": "SN candidate"}
    assert plan.predicate_realization.residual is None

    call = bind_endpoint(step, plan, EndpointRegistry(), reference_time=NOW)
    assert call.params["class"] == "SN candidate"
    assert call.params["startdate"] == "2026-10-21T12:34:56.123456Z"
    assert call.params["stopdate"] == "2026-10-28T12:34:56.123456Z"
    latests = EndpointRegistry().resolve("fink", "ztf", "latests")
    assert latests.params["n"]["default"] == 100


def test_fink_search_without_class_is_deferred_before_execution(graph):
    step = lower_surface(
        parse_surface_script("objects from ztf via fink")
    ).workflow.steps[0]

    evidence = validate_step_capabilities(step, graph)
    assert evidence.status == "deferred"
    assert "required physical parameters ('class',)" in evidence.source_results[0].reason
    with pytest.raises(PlanningDeferredError, match="required physical parameters"):
        plan_step(step, graph)

    validation = validate_dsl(
        "objects from ztf via fink", graph=graph, continue_from=None
    )
    assert not validation.is_runnable
    assert isinstance(validation.lowering_error, SurfaceLoweringError)


def test_fink_search_executes_against_fixture_latest_alert(graph):
    class RecordedTransport:
        name = "fixture"

        def __init__(self):
            self.calls = []

        def execute(self, spec, params, headers=None):
            del headers
            self.calls.append((spec.endpoint, dict(params)))
            return TransportResult(
                payload=[{
                    "i:objectId": "ZTF21abfmbix",
                    "v:classification": "SN candidate",
                }],
                method=spec.method,
                url=spec.url,
                status_code=200,
                content_type="application/json",
                raw_size_bytes=64,
            )

    registry = EndpointRegistry()
    transport = RecordedTransport()
    executor = RegistryEndpointExecutor(
        registry=registry, transports={"rest": transport}
    )
    result = execute_dsl(
        SEARCH,
        graph=graph,
        registry=registry,
        executor=executor,
        reference_time=NOW,
        continue_from=None,
    )

    endpoint, params = transport.calls[0]
    assert endpoint == "latests"
    assert params == {
        "class": "SN candidate",
        "startdate": "2026-10-21T12:34:56.123456Z",
        "stopdate": "2026-10-28T12:34:56.123456Z",
        "n": 100,
        "color": False,
        "output-format": "json",
    }
    assert len(result.portfolios) == 1
    assert any(
        record.semantic_type == "classification@fink"
        and record.fields["best.class"] == "SN candidate"
        for record in result.portfolios[0].records
    )


@pytest.mark.parametrize("operator", ["!=", "<", "<=", ">", ">="])
def test_fink_class_recipe_does_not_invent_non_equality_class_filters(graph, operator):
    source = (
        "objects from ztf via fink\n"
        f'where classification.best.class {operator} "SN candidate"\n'
    )
    validation = validate_dsl(source, graph=graph, continue_from=None)

    assert not validation.is_runnable
    assert validation.lowering_error is not None
    assert "required physical parameters ('class',)" in str(validation.lowering_error)
