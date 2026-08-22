"""Offline contracts for the live cross-broker material-lineage matrix."""

import pytest

from alertissimo.orchestration.runtime import CandidateInputRef, MaterialInputRef
from scripts.live_dsl_material_lineage import (
    SCENARIOS,
    assert_plan_contract,
    build_dsl,
    compile_and_plan,
)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.name)
def test_live_matrix_rows_compile_to_expected_cross_broker_roles(scenario):
    dsl, workflow, run = compile_and_plan(scenario)

    assert dsl == build_dsl(scenario)
    assert_plan_contract(scenario, workflow, run)
    assert len(run.steps) == 3

    search, first_get, second_get = run.steps
    assert search.material_input_from is None
    assert search.candidate_input_from is None

    assert first_get.endpoint_plans[0].candidate_input_from == CandidateInputRef(
        step_index=0
    )
    assert second_get.endpoint_plans[0].candidate_input_from == CandidateInputRef(
        step_index=0
    )
    assert first_get.material_input_from == MaterialInputRef(step_index=0)
    assert second_get.material_input_from == MaterialInputRef(step_index=1)
    assert first_get.candidate_input_from is None
    assert second_get.candidate_input_from is None

    assert getattr(workflow.steps[1], "target", None) is None
    assert getattr(workflow.steps[2], "target", None) is None


def test_live_matrix_rotates_each_broker_through_more_than_one_role():
    discovery_brokers = {scenario.discovery_broker for scenario in SCENARIOS}
    enrichment_brokers = {
        broker
        for scenario in SCENARIOS
        for _, broker in scenario.enrichments
    }

    assert discovery_brokers == {"alerce", "antares", "fink", "lasair"}
    assert enrichment_brokers == {"alerce", "antares", "fink", "lasair"}
    assert discovery_brokers == enrichment_brokers
