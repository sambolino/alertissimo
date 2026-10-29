"""Time intent and syntax only; first/last need later provider activation."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from alertissimo.api import validate_dsl
from alertissimo.data_layer.execution import EndpointRegistry
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.data_layer.transforms.request import RequestTransformError, apply_binding_adapter
from alertissimo.data_layer.transforms.temporal import resolve_time_context
from alertissimo.dsl import DSLParseError, SurfaceLoweringError, lower_surface, parse_surface_fragment, parse_surface_script
from alertissimo.dsl.surface import WithinClause
from alertissimo.orchestration.binding import ParameterBindingError, bind_endpoint
from alertissimo.orchestration.ir import TimeContext, WorkflowIR
from alertissimo.orchestration.planner import PlanningDeferredError, plan_step
from alertissimo.orchestration.validation import validate_step_capabilities


NOW = datetime(2026, 10, 29, 12, 34, 56, 123456, tzinfo=timezone.utc)
ADAPTER = "alertissimo.data_layer.transforms.temporal:time_bound"


def source(clause):
    return f'objects from ztf via fink\n{clause}\nwhere classification.best.class = "SN candidate"\n'


def lower(clause):
    return lower_surface(parse_surface_script(source(clause))).workflow


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


@pytest.mark.parametrize("prefix,mode", [("", "detection"), ("first ", "first"), ("last ", "last"), ("FiRsT\t", "first")])
def test_relative_spelling_survives_surface_ir_and_json_round_trip(prefix, mode):
    surface = parse_surface_script(source(prefix + "within 7d"))
    clause = surface.clauses[0]
    assert isinstance(clause, WithinClause) and clause.mode == mode
    assert clause.duration.value == 7 and clause.relative_to == "now"
    workflow = lower_surface(surface).workflow
    context = workflow.steps[0].time_context
    assert context.mode == mode and context.window == timedelta(days=7)
    assert context.start_time is None and context.end_time is None
    assert WorkflowIR.model_validate_json(workflow.model_dump_json()) == workflow
    resolved = resolve_time_context(context.model_dump(), NOW)
    assert resolved == {"start": NOW - timedelta(days=7), "end": NOW, "mode": mode}
    assert context.relative_to == "now"  # resolving never replaces intent


@pytest.mark.parametrize("bounds", [
    '["2026-10-01T00:00:00Z", "2026-10-08T00:00:00Z"]',
    '[2026-10-01T00:00:00Z, 2026-10-08T00:00:00Z]',
    '2026-10-01T00:00:00Z, 2026-10-08T00:00:00Z',
    '"2026-10-01T00:00:00Z", "2026-10-08T00:00:00Z"',
])
@pytest.mark.parametrize("prefix,mode", [("", "detection"), ("first ", "first"), ("last ", "last")])
def test_bracketed_and_legacy_date_pairs_lower_to_the_same_explicit_intent(bounds, prefix, mode):
    context = lower(prefix + "within " + bounds).steps[0].time_context
    assert context == TimeContext(mode=mode, start_time="2026-10-01T00:00:00Z", end_time="2026-10-08T00:00:00Z")
    assert resolve_time_context(context.model_dump(), None) == {
        "start": datetime(2026, 10, 1, tzinfo=timezone.utc),
        "end": datetime(2026, 10, 8, tzinfo=timezone.utc), "mode": mode,
    }


def test_explicit_offsets_and_subday_precision_are_preserved_without_a_clock():
    context = lower('within ["2026-10-01T02:00:00.123456+02:00", "2026-10-01T00:00:00.123456Z"]').steps[0].time_context
    resolved = resolve_time_context(context.model_dump(), None)
    assert resolved["start"] == resolved["end"] == datetime(2026, 10, 1, 0, 0, 0, 123456, tzinfo=timezone.utc)
    assert apply_binding_adapter(ADAPTER, {"time_context": resolved}, options={"bound": "range", "encoding": "utc_iso"}) == [
        "2026-10-01T00:00:00.123456Z", "2026-10-01T00:00:00.123456Z",
    ]


@pytest.mark.parametrize("clause", [
    'within ["2026-10-01T00:00:00Z", "2026-10-08T00:00:00Z"',
    'within ["2026-10-01T00:00:00Z"]',
    'within ["2026-10-01T00:00:00Z", ]',
    'within [[2026-10-01, 2026-10-08]]',
    'within [2026-10-01, 2026-10-08, 2026-10-09]',
    'first last within 7d', 'any within 7d', 'first within',
])
def test_malformed_or_unrequested_spelling_is_not_accepted(clause):
    with pytest.raises(DSLParseError):
        parse_surface_script(source(clause))


@pytest.mark.parametrize("mode", ["first", "last"])
def test_modes_keep_candidate_clause_scope_and_do_not_become_continuation_filters(mode):
    with pytest.raises(DSLParseError, match="initial candidate pass"):
        parse_surface_script(f"objects from ztf\nfilter exists summary\n{mode} within 7d\n")
    with pytest.raises(DSLParseError, match="lookup candidates"):
        parse_surface_script(f"object ZTF20acpwljl from ztf\n{mode} within 7d\n")
    with pytest.raises(DSLParseError):
        parse_surface_fragment(f"{mode} within 7d\n")
    with pytest.raises(SurfaceLoweringError, match="only one top-level within"):
        lower_surface(parse_surface_script(f"objects from ztf\nwithin 7d\n{mode} within 7d\n"))


def test_match_temporal_tolerance_remains_separate():
    parsed = parse_surface_script("objects from ztf\nfirst within 7d\nmatch from icecube within 3d on position inside 2deg\n")
    assert parsed.clauses[0].mode == "first"
    assert parsed.clauses[1].within.value == 3 and parsed.clauses[1].within.unit == "d"


@pytest.mark.parametrize("clause", [
    'within ["not a date", "2026-10-08T00:00:00Z"]',
    'within ["2026-10-09T00:00:00Z", "2026-10-08T00:00:00Z"]',
])
def test_bad_or_reversed_dates_fail_lowering(clause):
    with pytest.raises(SurfaceLoweringError) as raised:
        lower(clause)
    assert raised.value.code == "invalid_time_window"


def test_old_serialized_context_defaults_to_detection_existence():
    context = TimeContext.model_validate_json('{"start_time":"2026-10-01T00:00:00Z","end_time":"2026-10-08T00:00:00Z"}')
    assert context.mode == "detection"
    with pytest.raises(ValidationError, match="mode"):
        TimeContext(mode="any")
    with pytest.raises(ValidationError, match="mode"):
        WithinClause(mode="any", duration={"value": 7, "unit": "d"}, relative_to="now")
    assert lower("first within 7d") != lower("within 7d")
    assert lower("last within 7d") != lower("first within 7d")


@pytest.mark.parametrize("mode", ["first", "last"])
def test_new_modes_defer_before_clock_or_provider_execution(graph, monkeypatch, mode):
    class NoClock:
        @staticmethod
        def now(*args):
            raise AssertionError("validation must not sample a clock")
    monkeypatch.setattr("alertissimo.orchestration.pipeline.datetime", NoClock)
    monkeypatch.setattr("alertissimo.orchestration.binding.binder.datetime", NoClock)
    result = validate_dsl(source(f"{mode} within 7d"), graph=graph, continue_from=None)
    assert not result.is_runnable
    step = lower(f"{mode} within 7d").steps[0]
    evidence = validate_step_capabilities(step, graph)
    assert evidence.status == "deferred" and not evidence.candidates
    assert f"{mode} within requires a declared candidate-time translation" in evidence.source_results[0].reason
    with pytest.raises(PlanningDeferredError, match="declared candidate-time translation"):
        plan_step(step, graph)


def test_existing_fink_default_still_validates_and_binds_the_same_physical_parameters(graph):
    result = validate_dsl(source("within 7d"), graph=graph, continue_from=None)
    assert result.is_runnable, result.lowering_error
    step = result.compilation.workflow.steps[0]
    plan, = plan_step(step, graph)
    bound = bind_endpoint(step, plan, EndpointRegistry(), reference_time=NOW)
    assert bound.params == {"class": "SN candidate", "startdate": "2026-10-22T12:34:56.123456Z", "stopdate": "2026-10-29T12:34:56.123456Z"}


@pytest.mark.parametrize("mode", ["first", "last"])
def test_bypassing_planning_cannot_drop_the_mode_during_existing_window_encoding(graph, mode):
    ordinary = lower("within 7d").steps[0]
    plan, = plan_step(ordinary, graph)
    new_intent = lower(f"{mode} within 7d").steps[0]
    with pytest.raises(ParameterBindingError, match="declared candidate-time translation"):
        bind_endpoint(new_intent, plan, EndpointRegistry(), reference_time=NOW)
    resolved = resolve_time_context(new_intent.time_context.model_dump(), NOW)
    with pytest.raises(RequestTransformError, match="declared candidate-time translation"):
        apply_binding_adapter(ADAPTER, {"time_context": resolved}, options={"bound": "start", "encoding": "utc_iso"})
