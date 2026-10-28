"""Fixed-clock contracts for discovery binding and continuation; no HTTP calls."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import shutil

import pytest
import yaml

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import EndpointRegistry, ExecutionResult
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance
from alertissimo.data_layer.runtime.capability_graph import CapabilityGraphError, build_capability_graph
from alertissimo.data_layer.transforms.request import apply_binding_adapter
from alertissimo.orchestration.binding import bind_endpoint, bind_endpoint_calls, bind_workflow_run
from alertissimo.orchestration.incremental import IncrementalExecutionError, execute_incremental_workflow_run
from alertissimo.orchestration.ir import GetLightcurveStep, SemanticSearchStep, Source, TargetSelector, TimeContext, WorkflowIR
from alertissimo.orchestration.planner import PlanningDeferredError, plan_step, plan_workflow
from alertissimo.orchestration.runtime import EndpointPlan, WorkflowExecutionError


ADAPTER = "alertissimo.data_layer.transforms.temporal:time_bound"
NOW = datetime(2026, 10, 28, 12, 34, 56, 123456, tzinfo=timezone.utc)
START = "2026-10-21T12:34:56.123456Z"
STOP = "2026-10-28T12:34:56.123456Z"
DSL = "objects from lsst via alerce\nwithin 7d\n"


def edit_yaml(path, update):
    doc = yaml.safe_load(path.read_text())
    update(doc)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def contract(tmp_path, *, origins=("lsst",), encoding="utc_iso", ranged=False, fanout=False):
    """Author test-only temporal inputs without claiming upstream API support."""
    root = tmp_path / "providers"
    bounds = {"window": "range"} if ranged else {"window_start": "start", "window_end": "end"}
    for origin in origins:
        destination = root / "alerce" / origin
        shutil.copytree(PROVIDERS_ROOT / "alerce" / origin, destination)

        def endpoints(doc):
            for name in ("query_objects", "query_lightcurve") if fanout else ("query_objects",):
                for parameter, bound in bounds.items():
                    doc["endpoints"][name]["params"][parameter] = {
                        "type": "array" if ranged else "string" if encoding == "utc_iso" else "number",
                        "required": name == "query_objects", "bind": "time_context",
                        "binding": {"adapter": ADAPTER, "adapter_options": {"bound": bound, "encoding": encoding}},
                    }

        def recipes(doc):
            operations = ("semantic_search", "cone_search", "get_lightcurve") if fanout else ("semantic_search", "cone_search")
            for op in operations:
                for parameter in bounds:
                    doc["recipes"][op][0]["calls"][0].setdefault("params", {})[parameter] = {"from": "step.time_context"}

        edit_yaml(destination / "endpoints.yaml", endpoints)
        edit_yaml(destination / "capabilities.yaml", recipes)
    return root


def search(origins=("lsst",), context=None):
    return SemanticSearchStep(
        sources=[Source(broker="alerce", origin=origin) for origin in origins], semantic_type="summary",
        time_context=context if context is not None else TimeContext(window=timedelta(days=7), relative_to="now"),
    )


class FixtureExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        assert endpoint == "query_objects"
        self.calls.append((origin, dict(params)))
        rows = [{"oid": 123 if origin == "lsst" else "ZTF-time"}]
        return ExecutionResult(
            payload=rows if origin == "lsst" else {"items": rows},
            execution_provenance=InternalExecutionProvenance(
                InternalExecutionId(f"execution:clock:{len(self.calls)}"), broker, origin, endpoint,
                params=params, status="success", transport="fixture",
            ),
        )


def test_public_validation_keeps_relative_intent_and_never_reads_the_binding_clock(tmp_path, monkeypatch):
    root = contract(tmp_path)
    graph = build_capability_graph(root)

    class NoClock:
        @staticmethod
        def now(*args):
            raise AssertionError("validation must not sample a clock")

    monkeypatch.setattr("alertissimo.orchestration.binding.binder.datetime", NoClock)
    monkeypatch.setattr("alertissimo.orchestration.pipeline.datetime", NoClock)
    validation = validate_dsl(DSL, graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    context = validation.compilation.workflow.steps[0].time_context
    assert context.window == timedelta(days=7) and context.start_time is None
    plan, = plan_step(validation.compilation.workflow.steps[0], graph)
    assert plan.request_params == {}
    assert plan.parameter_sources["window_start"] == ("time_context",)


def test_relative_binding_is_fixed_clock_and_preserves_ir_after_plan_round_trip(tmp_path):
    root = contract(tmp_path)
    step = search()
    before = step.model_dump_json()
    plan, = plan_step(step, build_capability_graph(root))
    plan = EndpointPlan.model_validate_json(plan.model_dump_json())
    call = bind_endpoint(step, plan, EndpointRegistry(root), reference_time=NOW)
    assert call.params == {"window_start": START, "window_end": STOP}
    offset_call = bind_endpoint(step, plan, EndpointRegistry(root),
                               reference_time=NOW.astimezone(timezone(timedelta(hours=2))))
    assert offset_call.params == call.params
    assert step.model_dump_json() == before
    assert plan.request_params == {}


@pytest.mark.parametrize("encoding,expected", [
    ("utc_iso", ["2000-01-01T00:00:00.000000Z", "2000-01-02T12:00:00.000000Z"]),
    ("mjd", [51544.0, 51545.5]),
    ("jd", [2451544.5, 2451546.0]),
])
def test_absolute_range_encodes_utc_offsets_without_moving_boundaries(tmp_path, encoding, expected):
    root = contract(tmp_path, encoding=encoding, ranged=True)
    context = TimeContext(start_time="2000-01-01T02:00:00+02:00", end_time="2000-01-02T14:00:00+02:00")
    step = search(context=context)
    plan, = plan_step(step, build_capability_graph(root))
    call = bind_endpoint(step, plan, EndpointRegistry(root), reference_time=NOW)
    assert call.params["window"] == expected


def test_utc_iso_keeps_microseconds_and_utc_day_numbers_keep_subday_precision():
    resolved = {"start": NOW, "end": NOW}
    assert apply_binding_adapter(ADAPTER, {"time_context": resolved}, options={"bound": "start", "encoding": "utc_iso"}) == STOP
    midnight = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    for encoding in ("mjd", "jd"):
        value = apply_binding_adapter(ADAPTER, {"time_context": resolved}, options={"bound": "end", "encoding": encoding})
        base = apply_binding_adapter(ADAPTER, {"time_context": {"end": midnight}}, options={"bound": "end", "encoding": encoding})
        assert (value - base) * 86400 == pytest.approx((NOW - midnight).total_seconds(), abs=0.0001, rel=0)


def test_one_occurrence_uses_one_clock_for_both_bounds_and_all_sources(tmp_path, monkeypatch):
    root = contract(tmp_path, origins=("lsst", "ztf"))
    samples = []

    class AdvancingClock:
        @staticmethod
        def now(tz):
            samples.append(1)
            return NOW + timedelta(minutes=len(samples) - 1)

    monkeypatch.setattr("alertissimo.orchestration.pipeline.datetime", AdvancingClock)
    executor = FixtureExecutor()
    result = execute_dsl("objects from lsst, ztf via alerce\nwithin 7d\n", graph=build_capability_graph(root),
                         registry=EndpointRegistry(root), executor=executor, continue_from=None)
    assert len(samples) == 1
    assert len(executor.calls) == 2
    assert all(params == {"window_start": START, "window_end": STOP} for _, params in executor.calls)
    assert result.staged.bindings[0].reference_time == NOW
    assert all(execution.params["window_end"] == STOP for portfolio in result.portfolios for execution in portfolio.executions)


def test_static_binding_and_fanout_share_the_same_occurrence_clock(tmp_path, monkeypatch):
    root = contract(tmp_path, fanout=True)
    graph, registry = build_capability_graph(root), EndpointRegistry(root)
    run = plan_workflow(WorkflowIR(steps=[search()]), graph)
    binding, = bind_workflow_run(run, registry, reference_time=NOW)
    assert binding.reference_time == NOW
    assert binding.bound_calls[0].params["window_end"] == STOP
    step = GetLightcurveStep(target=TargetSelector(ids=["1", "2"], kind="object"),
                            time_context=TimeContext(window=timedelta(days=7), relative_to="now"))
    plan = EndpointPlan(broker="alerce", origin="lsst", endpoint="query_lightcurve", parameter_sources={
        "oid": ("target", "ids"), "window_start": ("time_context",), "window_end": ("time_context",),
    })
    samples = []

    class Clock:
        @staticmethod
        def now(tz):
            samples.append(1)
            return NOW + timedelta(minutes=len(samples) - 1)

    monkeypatch.setattr("alertissimo.orchestration.binding.binder.datetime", Clock)
    calls = bind_endpoint_calls(step, plan, registry)
    assert len(samples) == 1 and len(calls) == 2
    assert [call.params["oid"] for call in calls] == [1, 2]
    assert all(call.params["window_end"] == STOP for call in calls)


def test_continuation_pins_old_bounds_while_fresh_and_appended_searches_use_new_clock(tmp_path):
    root = contract(tmp_path)
    graph, registry, executor = build_capability_graph(root), EndpointRegistry(root), FixtureExecutor()
    first = execute_dsl(DSL, graph=graph, registry=registry, executor=executor, continue_from=None, reference_time=NOW)
    before = first.to_dict()
    later = NOW + timedelta(days=1)
    continued = execute_dsl("filter exists summary.identity.object_id", graph=graph, registry=registry,
                            executor=executor, continue_from=first, reference_time=later)
    assert len(executor.calls) == 1
    assert continued.staged.bindings[0].reference_time == NOW
    assert first.to_dict() == before
    extended = WorkflowIR(steps=[*first.workflow.steps, search()])
    appended = execute_incremental_workflow_run(plan_workflow(extended, graph), first.staged, registry, executor,
                                               reference_time=later)
    assert len(executor.calls) == 2
    assert appended.bindings[0].reference_time == NOW and appended.bindings[1].reference_time == later
    assert executor.calls[-1][1]["window_end"] == "2026-10-29T12:34:56.123456Z"
    fresh = execute_dsl(DSL, graph=graph, registry=registry, executor=executor, continue_from=None, reference_time=later)
    assert len(executor.calls) == 3
    assert fresh.staged.bindings[0].reference_time == later


def test_changed_temporal_prefix_or_clock_metadata_cannot_replay_stale_results(tmp_path):
    root = contract(tmp_path)
    graph, registry, executor = build_capability_graph(root), EndpointRegistry(root), FixtureExecutor()
    first = execute_dsl(DSL, graph=graph, registry=registry, executor=executor, continue_from=None, reference_time=NOW)
    changed = WorkflowIR(steps=[search(context=TimeContext(window=timedelta(days=8), relative_to="now"))])
    with pytest.raises(IncrementalExecutionError, match="semantic workflow prefix"):
        execute_incremental_workflow_run(plan_workflow(changed, graph), first.staged, registry, executor)
    tampered = replace(first.staged, bindings=(replace(first.staged.bindings[0], reference_time=NOW + timedelta(days=1)),))
    with pytest.raises(WorkflowExecutionError, match="previous physical-call"):
        execute_incremental_workflow_run(plan_workflow(first.workflow, graph), tampered, registry, executor)
    assert len(executor.calls) == 1


@pytest.mark.parametrize("context", [
    TimeContext(window=timedelta(days=-1), relative_to="now"),
    TimeContext(window=timedelta(days=1), relative_to="yesterday"),
    TimeContext(window=timedelta(days=1), relative_to="now", sampling="nightly"),
    TimeContext(window=timedelta(days=1), relative_to="now", offset=timedelta(0)),
    TimeContext(start_time="2026-10-01T00:00:00", end_time="2026-10-02T00:00:00"),
    TimeContext(start_time=NOW),
    TimeContext(window=timedelta(days=1), relative_to="now", start_time=NOW, end_time=NOW),
])
def test_unrepresentable_time_context_is_deferred_without_sampling_a_clock(tmp_path, context):
    root = contract(tmp_path)
    with pytest.raises(PlanningDeferredError, match="time_context"):
        plan_step(search(context=context), build_capability_graph(root))


def test_missing_window_and_naive_reference_fail_before_provider_execution(tmp_path):
    root = contract(tmp_path)
    graph, registry, executor = build_capability_graph(root), EndpointRegistry(root), FixtureExecutor()
    assert not validate_dsl("objects from lsst via alerce", graph=graph, continue_from=None).is_runnable
    with pytest.raises(ValueError, match="timezone-aware"):
        execute_dsl(DSL, graph=graph, registry=registry, executor=executor, continue_from=None,
                    reference_time=NOW.replace(tzinfo=None))
    assert executor.calls == []


@pytest.mark.parametrize("change", ["partial", "nested", "constant_end", "encoding", "bound"])
def test_time_binding_declarations_must_encode_the_whole_context_and_both_bounds(tmp_path, change):
    root = contract(tmp_path)
    destination = root / "alerce" / "lsst"
    if change in {"partial", "nested", "constant_end"}:
        def invalid(doc):
            params = doc["recipes"]["semantic_search"][0]["calls"][0]["params"]
            if change == "partial":
                params.pop("window_end")
            elif change == "nested":
                params["window_start"] = {"from": "step.time_context.start_time"}
            else:
                params["window_end"] = {"value": STOP}
        edit_yaml(destination / "capabilities.yaml", invalid)
    else:
        def invalid(doc):
            options = doc["endpoints"]["query_objects"]["params"]["window_start"]["binding"]["adapter_options"]
            options[change] = "unsupported"
        edit_yaml(destination / "endpoints.yaml", invalid)
    with pytest.raises(CapabilityGraphError):
        build_capability_graph(root)
