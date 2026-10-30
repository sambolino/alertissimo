"""Public regressions for predicate loss and premature discovery pruning.

Synthetic two-object responses keep selection and call attribution explicit.
The executor never contacts a provider; no captured payloads are modified.
"""

from copy import deepcopy
from itertools import count

import pytest

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import (
    DSLParseError, FilterClause, SurfaceLoweringError, SurfaceScript,
    lower_surface, parse_surface_script,
)
from alertissimo.orchestration.normalization import summary_object_identity
from alertissimo.orchestration.planner import PlanningDeferredError


A, B = "ZTF21abfmbix", "ZTF20acpwljl"
LOOKUP = f"objects {A}, {B} from ztf via alerce\n"
CONE = "objects from ztf via alerce\ninside (124.87996115142856, -6.0205001, 5arcsec)\n"
CONDITION = 'classification@fink:fink.best.class = "SN candidate"'


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def identities(portfolios):
    return {summary_object_identity(portfolio) for portfolio in portfolios}


def summary(oid):
    return {"oid": oid, "meanra": 124.87996115142856, "meandec": -6.0205001,
            "firstmjd": 58000.0, "lastmjd": 61001.0 if oid == A else 59000.0, "ndet": 2}


class ReplayExecutor:
    def __init__(self):
        self.calls = []
        self.ids = count()

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        params = dict(params or {})
        assert origin == "ztf"
        self.calls.append((broker, endpoint, deepcopy(params)))
        if (broker, endpoint) == ("alerce", "query_object"):
            assert params["oid"] in {A, B}
            payload = summary(params["oid"])
        elif (broker, endpoint) == ("alerce", "query_objects"):
            payload = {"items": [summary(A), summary(B)]}
        else:
            assert (broker, endpoint) == ("fink", "objects")
            payload = [
                {"i:objectId": oid, "i:candid": 1000 + index * 10 + point,
                 "i:jd": 2460000.5 + point, "i:fid": 1,
                 "i:magpsf": 19.0 + point / 10, "i:sigmapsf": 0.1,
                 "i:ra": 124.87996115142856, "i:dec": -6.0205001,
                 "i:ndethist": 2, "v:classification": "SN candidate" if oid == A else "AGN"}
                for index, oid in enumerate(params["objectId"].split(","))
                for point in range(2)
            ]
        return ExecutionResult(
            payload=payload,
            execution_provenance=InternalExecutionProvenance(
                internal_execution_id=InternalExecutionId(f"preservation:{next(self.ids)}"),
                broker=broker, origin=origin, endpoint=endpoint, params=params,
            ),
        )


@pytest.mark.parametrize("tail", [
    'with classification via fink where best.class = "SN candidate"\n',
    f"where {CONDITION}\n",
    f"where {CONDITION}\nwith classification from fink via fink\n",
    f"with classification from fink via fink\nwhere {CONDITION}\n",
])
def test_lookup_conditions_retrieve_then_select_instead_of_disappearing(graph, tail):
    executor = ReplayExecutor()
    source = LOOKUP + tail
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    assert executor.calls == []
    result = execute_dsl(source, graph=graph, executor=executor, continue_from=None)

    assert [step.op for step in result.workflow.steps] == ["lookup", "get_classification", "filter"]
    assert identities(result.portfolios) == {("ztf", A)}
    assert identities(result.result.steps[1].portfolios) == {("ztf", A), ("ztf", B)}
    assert [endpoint for _, endpoint, _ in executor.calls] == ["query_object", "query_object", "objects"]
    assert executor.calls[-1][2] == {"objectId": f"{A},{B}"}
    # Candidate selection retains all observations of the survivor.
    assert sum(record.semantic_type == "measurement@ztf:fink"
               for portfolio in result.portfolios for record in portfolio.records) == 2


def test_fresh_scoped_lookup_matches_continuation_without_changing_prior_result(graph):
    clause = 'with classification via fink where best.class = "SN candidate"\n'
    fresh = execute_dsl(LOOKUP + clause, graph=graph, executor=ReplayExecutor(), continue_from=None)
    executor = ReplayExecutor()
    first = execute_dsl(LOOKUP, graph=graph, executor=executor, continue_from=None)
    snapshot = first.to_dict()
    assert validate_dsl(clause, graph=graph, continue_from=first).is_runnable
    second = execute_dsl(clause, graph=graph, executor=executor, continue_from=first)

    assert identities(fresh.portfolios) == identities(second.portfolios) == {("ztf", A)}
    assert first.to_dict() == snapshot
    assert second.workflow.steps[:len(first.workflow.steps)] == first.workflow.steps
    assert [endpoint for _, endpoint, _ in executor.calls] == ["query_object", "query_object", "objects"]


def test_lookup_conditions_run_before_an_explicit_later_filter(graph):
    source = (LOOKUP + 'with classification via fink where best.class = "SN candidate"\n'
              + "filter summary.detection_count >= 1\n")
    result = execute_dsl(source, graph=graph, executor=ReplayExecutor(), continue_from=None)
    assert [step.op for step in result.workflow.steps] == ["lookup", "get_classification", "filter", "filter"]
    assert identities(result.result.steps[2].portfolios) == {("ztf", A)}
    assert identities(result.portfolios) == {("ztf", A)}


def test_summary_only_lookup_condition_is_not_silently_ignored(graph):
    executor = ReplayExecutor()
    result = execute_dsl(LOOKUP + "where summary.detection_count > 2\n",
                         graph=graph, executor=executor, continue_from=None)
    assert [step.op for step in result.workflow.steps] == ["lookup", "filter"]
    assert result.portfolios == ()
    assert len(executor.calls) == 2


def test_lookup_adjacent_confirmation_keeps_its_proposition_in_confirm():
    workflow = lower_surface(parse_surface_script(
        LOOKUP + 'where classification.best.class = "SN candidate"\nconfirm by 1 via fink\n'
    )).workflow
    assert [step.op for step in workflow.steps] == ["lookup", "confirm"]
    assert workflow.steps[1].predicate is not None


@pytest.mark.parametrize("clause", [
    "inside (1, 2, 5arcsec)", "within 7d", "first within 7d", "latest 1",
])
def test_unrepresented_lookup_constraints_fail_before_execution(graph, clause):
    source = LOOKUP + clause + "\n"
    with pytest.raises(DSLParseError, match="lookup candidates cannot carry search constraints"):
        parse_surface_script(source)
    assert not validate_dsl(source, graph=graph, continue_from=None).is_runnable
    executor = ReplayExecutor()
    with pytest.raises(DSLParseError, match="lookup candidates cannot carry search constraints"):
        execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    assert executor.calls == []


@pytest.mark.parametrize("clause", [
    "where summary.detection_count > 2", "inside (1, 2, 5arcsec)",
    "within 7d", "latest 1",
])
def test_late_candidate_constraints_are_rejected_instead_of_dropped(graph, clause):
    source = CONE + "filter exists summary.identity.object_id\n" + clause + "\n"
    with pytest.raises(DSLParseError, match="initial candidate pass"):
        parse_surface_script(source)
    assert not validate_dsl(source, graph=graph, continue_from=None).is_runnable
    executor = ReplayExecutor()
    with pytest.raises(DSLParseError, match="initial candidate pass"):
        execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    assert executor.calls == []


@pytest.mark.parametrize("clause", [
    "where summary.detection_count > 2", "inside (1, 2, 5arcsec)",
    "within 7d", "latest 1",
])
def test_direct_surface_input_cannot_bypass_late_constraint_guard(clause):
    base = parse_surface_script(CONE)
    late = parse_surface_script("objects from ztf via alerce\n" + clause + "\n").clauses[0]
    surface = SurfaceScript(
        candidates=base.candidates,
        clauses=(*base.clauses, FilterClause(condition="exists summary.identity.object_id"), late),
    )
    with pytest.raises(SurfaceLoweringError) as caught:
        lower_surface(surface)
    assert caught.value.code == "late_candidate_constraint"


@pytest.mark.parametrize("source", [
    CONE + 'with classification via fink where best.class = "SN candidate"\n',
    CONE + 'where classification@fink:fink.best.class = "SN candidate"\n',
    "objects from ztf via lasair\ninside (124.87996115142856, -6.0205001, 5arcsec)\n"
    "where summary.detection_count >= 5\n",
])
def test_unavailable_discovery_material_defers_before_any_provider_call(graph, source):
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_valid and not validation.is_runnable
    assert "discovery residual requires material unavailable" in str(validation.lowering_error)
    executor = ReplayExecutor()
    with pytest.raises(PlanningDeferredError, match="discovery residual requires material unavailable"):
        execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    assert executor.calls == []


def test_available_discovery_residual_still_selects_from_real_material(graph):
    executor = ReplayExecutor()
    result = execute_dsl(CONE + "where summary.time.last_mjd < 60000\n",
                         graph=graph, executor=executor, continue_from=None)
    assert identities(result.portfolios) == {("ztf", B)}
    assert [endpoint for _, endpoint, _ in executor.calls] == ["query_objects"]


def test_dynamic_mapped_measurement_fields_remain_admitted(graph):
    source = ('objects from ztf via fink\nwithin 7d\n'
              'where classification.best.class = "SN candidate" and '
              'measurement@ztf:fink.photometry.g.psf.mag < 20\n')
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
