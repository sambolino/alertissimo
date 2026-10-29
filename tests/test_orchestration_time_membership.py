"""Synthetic recipe proofs exercise shared membership, not live provider support."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import shutil

import pytest
import yaml

from alertissimo.api import execute_dsl
from alertissimo.data_layer.execution import EndpointRegistry, ExecutionResult
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance, InternalRecordId, InternalRecordSource, SemanticRecord
from alertissimo.data_layer.runtime.capability_graph import CapabilityGraphError, build_capability_graph
from alertissimo.dsl import lower_surface, parse_surface_script
from alertissimo.orchestration.incremental import IncrementalExecutionError, execute_incremental_workflow_run
from alertissimo.orchestration.normalization import TimeSelectionError, StepPortfolioResult, apply_time_selection, normalize_workflow_execution, summary_object_identity
from alertissimo.orchestration.planner import PlanningDeferredError, plan_step, plan_workflow
from alertissimo.orchestration.runtime import EndpointPlan


NOW = datetime(2020, 6, 20, tzinfo=timezone.utc)  # UTC MJD 59020
IDS = tuple(f"ZTF20{letter * 7}" for letter in "abcd")
ROWS = [
    {"oid": IDS[0], "firstmjd": 59000, "lastmjd": 59030},
    {"oid": IDS[1], "firstmjd": 59000, "lastmjd": 59090},
    {"oid": IDS[2], "firstmjd": 59011, "lastmjd": 59050},
    {"oid": IDS[3], "firstmjd": 58990, "lastmjd": 59015},
]
HISTORY = {IDS[0]: [59000, 59012, 59030], IDS[1]: [59000, 59090],
           IDS[2]: [59011, 59050], IDS[3]: [58990, 59015]}


def edit(path, change):
    doc = yaml.safe_load(path.read_text())
    change(doc)
    path.write_text(yaml.safe_dump(doc, sort_keys=False))


def contract(tmp_path, *, mode="detection", complete=True):
    """Test-only complete scan/history or native summary-time request contract."""
    root = tmp_path / "providers"
    dest = root / "alerce/ztf"
    shutil.copytree(PROVIDERS_ROOT / "alerce/ztf", dest)
    native = mode != "detection"
    calls = [{"endpoint": "query_objects"}]
    if native:
        def endpoints(doc):
            doc["endpoints"]["query_objects"]["params"]["fixture_window"] = {
                "type": "array", "bind": "time_context",
                "binding": {"adapter": "alertissimo.data_layer.transforms.temporal:time_bound",
                            "adapter_options": {"mode": mode, "bound": "range", "encoding": "mjd"}},
            }
        edit(dest / "endpoints.yaml", endpoints)
        calls[0]["params"] = {"fixture_window": {"from": "step.time_context"}}
    else:
        calls.append({"endpoint": "query_lightcurve", "params": {
            "oid": {"from": {"call": 0, "path": "summary.identity.object_id"}},
        }})
    def recipes(doc):
        # Isolate history reuse from the unrelated optional forced-photometry
        # supplement. Production declarations are not modified by this fixture.
        doc["recipes"]["get_lightcurve"][0]["calls"] = doc["recipes"]["get_lightcurve"][0]["calls"][:1]
        doc["recipes"]["semantic_search"] = [{"calls": calls, "time_selection": {
            "mode": mode, "method": "native" if native else "material",
            "call": 0 if native else 1,
            "payload": "query_objects" if native else "query_lightcurve.detections",
            "complete": complete, "time_scale": "utc",
        }}]
    edit(dest / "capabilities.yaml", recipes)
    return root, dest


class FixtureExecutor:
    def __init__(self, rows=None, histories=None, *, invalid=False):
        self.rows = deepcopy(ROWS if rows is None else rows)
        self.histories = deepcopy(HISTORY if histories is None else histories)
        self.invalid = invalid
        self.calls = []

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        self.calls.append((endpoint, dict(params or {})))
        if endpoint == "query_objects":
            payload = {"items": deepcopy(self.rows)}
        elif endpoint == "query_lightcurve":
            oid = params["oid"]
            payload = {"detections": [
                {"oid": oid, "mjd": mjd, "candid": index + 1, "fid": 1, "magpsf": 20.0, "sigmapsf": 0.1}
                for index, mjd in enumerate(self.histories[oid])
            ], "non_detections": [{"oid": oid, "mjd": 59012, "fid": 1, "diffmaglim": 22.0}]}
            if self.invalid:
                payload["detections"][0]["mjd"] = "not numeric"
        else:
            assert endpoint == "query_probabilities"
            payload = []
        return ExecutionResult(payload=payload, execution_provenance=InternalExecutionProvenance(
            InternalExecutionId(f"execution:temporal:{len(self.calls)}"), broker, origin, endpoint,
            params=dict(params or {}), transport="fixture", status="success"))


def program(mode="detection", tail=""):
    prefix = "" if mode == "detection" else mode + " "
    return f"objects from ztf via alerce\n{prefix}within 10d\n{tail}"


def identities(portfolios):
    return {summary_object_identity(portfolio)[1] for portfolio in portfolios}


def run(tmp_path, *, mode="detection", complete=True, tail="", executor=None):
    root, dest = contract(tmp_path, mode=mode, complete=complete)
    graph, registry = build_capability_graph(root), EndpointRegistry(root)
    executor = executor or FixtureExecutor()
    result = execute_dsl(program(mode, tail), graph=graph, registry=registry, executor=executor,
                         continue_from=None, reference_time=NOW)
    return result, executor, graph, registry, dest


def test_history_overlap_is_not_a_match_and_nondetections_do_not_supply_a_witness(tmp_path):
    result, executor, _, _, _ = run(tmp_path, tail="with classification via alerce\n")
    assert identities(result.result.steps[0].portfolios) == {IDS[0], IDS[2], IDS[3]}
    assert identities(result.portfolios) == {IDS[0], IDS[2], IDS[3]}
    assert [params["oid"] for endpoint, params in executor.calls if endpoint == "query_probabilities"] == [IDS[0], IDS[2], IDS[3]]
    for portfolio in result.portfolios:
        oid = summary_object_identity(portfolio)[1]
        ordinary = [r for r in portfolio.records if r.internal_source is not None and r.internal_source.payload_key == "query_lightcurve.detections"]
        assert sorted(r.get("time.mjd") for r in ordinary) == HISTORY[oid]
    assert result.run.steps[0].time_reference == NOW
    proof = result.run.steps[0].endpoint_plans[0].time_selection
    assert proof.evidence_plan_index == 1 and proof.payload == "query_lightcurve.detections"
    restored = EndpointPlan.model_validate_json(result.run.steps[0].endpoint_plans[0].model_dump_json())
    assert restored.time_selection == proof
    offline = normalize_workflow_execution(result.staged.execution)
    assert identities(offline.steps[-1].portfolios) == identities(result.portfolios)


@pytest.mark.parametrize("mode,expected", [("first", IDS[2]), ("last", IDS[3])])
def test_native_summary_evidence_is_rechecked_before_latest_without_history_calls(tmp_path, mode, expected):
    result, executor, _, _, _ = run(tmp_path, mode=mode, tail="latest 1\n")
    assert identities(result.portfolios) == {expected}
    assert [endpoint for endpoint, _ in executor.calls] == ["query_objects"]
    assert executor.calls[0][1]["fixture_window"] == [59010.0, 59020.0]
    assert identities(normalize_workflow_execution(result.staged.execution).steps[0].portfolios) == {expected}


def test_positive_witness_needs_no_negative_coverage_claim(tmp_path):
    result, _, _, _, _ = run(tmp_path, complete=False, executor=FixtureExecutor(rows=ROWS[:1]))
    assert identities(result.portfolios) == {IDS[0]}


def test_absence_without_coverage_is_explicit_and_never_a_successful_empty_result(tmp_path):
    with pytest.raises(TimeSelectionError, match="insufficient temporal evidence"):
        run(tmp_path, complete=False)


def test_complete_empty_history_and_empty_discovery_are_valid_empty_results(tmp_path):
    result, _, _, _, _ = run(tmp_path / "history", executor=FixtureExecutor(rows=ROWS[:1], histories={IDS[0]: []}))
    assert not result.portfolios
    result, executor, _, _, _ = run(tmp_path / "scan", executor=FixtureExecutor(rows=[]))
    assert not result.portfolios and len(executor.calls) == 1


def test_reused_history_cannot_resurrect_rejected_candidates_or_fetch_again(tmp_path):
    result, executor, _, _, _ = run(tmp_path, tail="with lightcurve via alerce\n")
    assert identities(result.portfolios) == {IDS[0], IDS[2], IDS[3]}
    assert len(executor.calls) == 5  # discovery plus four history calls, no second fetch
    assert result.run.steps[1].endpoint_plans[0].execution_reuse_from is not None
    assert identities(normalize_workflow_execution(result.staged.execution).steps[1].portfolios) == identities(result.portfolios)


def test_continuation_pins_clock_replays_history_and_keeps_the_selected_ids(tmp_path):
    first, executor, graph, registry, _ = run(tmp_path)
    old_calls = len(executor.calls)
    second = execute_dsl("with classification via alerce\n", graph=graph, registry=registry,
                         executor=executor, continue_from=first,
                         reference_time=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert second.run.steps[0].time_reference == NOW
    assert len(executor.calls) == old_calls + 3
    assert identities(second.portfolios) == {IDS[0], IDS[2], IDS[3]}
    # Proof changes invalidate the physical prefix even with identical source text.
    old_plan = first.run.steps[0].endpoint_plans[0]
    changed_plan = old_plan.model_copy(update={"time_selection": old_plan.time_selection.model_copy(update={"complete": False})})
    changed_step = first.run.steps[0].model_copy(update={"endpoint_plans": (changed_plan, *first.run.steps[0].endpoint_plans[1:])})
    changed = first.run.model_copy(update={"steps": (changed_step,)})
    with pytest.raises(IncrementalExecutionError, match="physical plan"):
        execute_incremental_workflow_run(changed, first.staged, registry, executor)


def test_offline_relative_membership_does_not_sample_a_new_clock(tmp_path):
    result, _, _, _, _ = run(tmp_path)
    execution = result.staged.execution
    step = execution.run.steps[0].model_copy(update={"time_reference": None})
    broken = replace(execution, run=execution.run.model_copy(update={"steps": (step,)}))
    with pytest.raises(TimeSelectionError, match="pinned candidate time interval"):
        normalize_workflow_execution(broken)


@pytest.mark.parametrize("change,message", [
    ("optional", "required call"), ("mode", "invalid time selection mode"),
    ("payload", "ordinary photometry"), ("scale", "time_scale must be utc"),
    ("complete", "complete must be boolean"), ("native", "native selection requires"),
])
def test_invalid_evidence_declarations_fail_at_loading(tmp_path, change, message):
    root, dest = contract(tmp_path)
    def corrupt(doc):
        recipe = doc["recipes"]["semantic_search"][0]
        proof = recipe["time_selection"]
        if change == "optional":
            recipe["calls"][1]["required"] = False
        elif change == "mode":
            proof["mode"] = "any"
        elif change == "payload":
            proof["payload"] = "query_lightcurve.non_detections"
        elif change == "scale":
            proof["time_scale"] = "tai"
        elif change == "complete":
            proof["complete"] = "true"
        else:
            proof["method"] = "native"
    edit(dest / "capabilities.yaml", corrupt)
    with pytest.raises(CapabilityGraphError, match=message):
        build_capability_graph(root)


def test_wrong_mode_or_missing_window_is_not_admitted(tmp_path):
    root, _ = contract(tmp_path, mode="first")
    graph = build_capability_graph(root)
    for source in (program("last"), "objects from ztf via alerce\n"):
        step = lower_surface(parse_surface_script(source)).workflow.steps[0]
        with pytest.raises(PlanningDeferredError):
            plan_step(step, graph)


@pytest.mark.parametrize("mjd", [59010, 59020])
def test_interval_endpoints_are_inclusive_without_trimming_measurements(tmp_path, mjd):
    result, _, _, _, _ = run(tmp_path, complete=False,
                             executor=FixtureExecutor(rows=ROWS[:1], histories={IDS[0]: [mjd]}))
    assert identities(result.portfolios) == {IDS[0]}


@pytest.mark.parametrize("broker", ["alerce", "fink"])
def test_another_execution_or_broker_cannot_supply_the_witness(tmp_path, broker):
    result, _, _, _, _ = run(tmp_path, executor=FixtureExecutor(rows=ROWS[1:2]))
    view = result.result.steps[0]
    raw = StepPortfolioResult(step_index=0, executions=view.executions).portfolios[0]
    other = InternalExecutionProvenance(InternalExecutionId("execution:other"), broker, "ztf", "query_lightcurve")
    witness = SemanticRecord(InternalRecordId("record:unrelated"), f"detection@ztf:{broker}",
                             {"time.mjd": 59012, "photometry.g.psf.mag": 19},
                             InternalRecordSource(other.internal_execution_id, "query_lightcurve.detections", "detections[]"))
    augmented = replace(raw, records=raw.records + (witness,), executions=raw.executions + (other,))
    selected = apply_time_selection(result.workflow.steps[0], result.run.steps[0],
                                    replace(view, materialized_portfolios=(augmented,)))
    assert not selected.portfolios


def test_mapping_possibility_cannot_replace_a_requested_projection(tmp_path):
    root, dest = contract(tmp_path, mode="first")
    def endpoints(doc):
        endpoint = doc["endpoints"]["query_objects"]
        endpoint["params"]["fixture_columns"] = {"type": "string"}
        endpoint["projection"] = {"supports_columns": True, "param": "fixture_columns"}
    edit(dest / "endpoints.yaml", endpoints)
    def recipes(doc):
        doc["recipes"]["semantic_search"][0]["calls"][0]["params"]["fixture_columns"] = {"value": "oid"}
    edit(dest / "capabilities.yaml", recipes)
    with pytest.raises(CapabilityGraphError, match="mapped time evidence"):
        build_capability_graph(root)


def test_continuation_checks_the_pinned_clock_even_without_physical_time_parameters(tmp_path):
    first, executor, graph, registry, _ = run(tmp_path)
    binding = first.staged.bindings[0]
    tampered = replace(first.staged, bindings=(replace(binding, reference_time=NOW + timedelta(days=1)),))
    with pytest.raises(IncrementalExecutionError, match="temporal reference is inconsistent"):
        execute_incremental_workflow_run(plan_workflow(first.workflow, graph), tampered, registry, executor)
    assert len(executor.calls) == 5
