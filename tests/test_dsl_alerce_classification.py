"""Public classification regressions using recorded rows and the real transport.

The client substitute implements the inspected 2.3.1 signature without **kwargs.
It makes no HTTP calls. Original capture IDs are used except in the two reported
ZTF examples, which replay the same probability rows under a controlled test ID.
"""

from collections import Counter
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.data_layer.runtime.record_builder import _semantic_identifier
from alertissimo.orchestration.normalization import summary_object_identity
from alertissimo.orchestration.planner import PlanningAmbiguityError, plan_workflow


FIXTURES = Path(__file__).parent / "fixtures" / "alerce"


def recorded_client(monkeypatch, origin):
    calls = []
    probabilities = json.loads((FIXTURES / origin / "query_probabilities.json").read_text())
    summary = json.loads((FIXTURES / origin / "query_object.json").read_text())

    class RecordedClient:
        def query_object(self, oid, format="json", survey=None):
            assert survey == origin and format == "json"
            calls.append(("query_object", oid, survey))
            return {**summary, "oid": oid}

        def query_probabilities(self, oid, format="json", survey=None, index=None, sort=None):
            assert survey == origin and format == "json"
            calls.append(("query_probabilities", oid, survey))
            return deepcopy(probabilities)

    monkeypatch.setitem(sys.modules, "alerce.core", SimpleNamespace(Alerce=RecordedClient))
    return calls, probabilities


def classification_records(portfolios):
    return [record for portfolio in portfolios for record in portfolio.records
            if record.semantic_type.startswith("classification@")]


@pytest.mark.parametrize("origin,oid,classifier", [
    ("ztf", "ZTF21abfmbix", None),
    ("ztf", "ZTF21abfmbix", "lc_classifier"),
    ("ztf", "ZTF18abbuksn", "missing_classifier"),
    ("lsst", "170587117485817955", None),
    ("lsst", "170587117485817955", "stamp_classifier_rubin_beta"),
    ("lsst", "170587117485817955", "missing_classifier"),
])
def test_public_lookup_classification_selects_locally_without_unsupported_keyword(
    monkeypatch, origin, oid, classifier,
):
    calls, rows = recorded_client(monkeypatch, origin)
    source = f"objects {oid} from {origin} via alerce\nwith classification"
    if classifier is not None:
        source += f" from {classifier}"
    source += " via alerce\n"
    validation = validate_dsl(source, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    assert calls == []
    result = execute_dsl(source, executor=RegistryEndpointExecutor(), continue_from=None)
    actual_oid = int(oid) if origin == "lsst" else oid
    assert calls == [("query_object", actual_oid, origin), ("query_probabilities", actual_oid, origin)]
    plan, = result.run.steps[1].endpoint_plans
    assert plan.endpoint == "query_probabilities"
    assert "classifier" not in plan.parameter_sources
    assert "classifier" not in plan.request_params
    assert {summary_object_identity(portfolio) for portfolio in result.portfolios} == {(origin, oid)}

    actual = classification_records(result.portfolios)
    if classifier is not None:
        assert {record.semantic_type for record in actual} <= {f"classification@{classifier}:alerce"}
    probability_records = [record for record in actual if any(field.startswith("assessment.") for field in record.fields)]
    expected_rows = [row for row in rows if classifier is None or _semantic_identifier(row["classifier_name"]) == classifier]

    def evidence(row):
        return row["classifier_name"], row["classifier_version"], row["class_name"], row["probability"], row["ranking"]

    def record_evidence(record):
        class_path = next(field for field in record.fields
                          if field.startswith("assessment.") and field.endswith(".class"))
        prefix = class_path.removesuffix(".class")
        return (
            record.fields["provenance.producer.name"], record.fields["provenance.producer.version"],
            record.fields[class_path], record.fields[f"{prefix}.probability"], record.fields[f"{prefix}.rank"],
        )

    assert Counter(map(record_evidence, probability_records)) == Counter(map(evidence, expected_rows))
    if classifier == "missing_classifier":
        assert actual == []
    # The semantic selection must not overwrite the original normalized audit.
    audit = result.result.steps[1].executions[0].portfolios
    assert len(classification_records(audit)) == len(rows)
    assert result.staged.execution.steps[1].executions[0].payload == rows
    if classifier is not None:
        assert result.result.steps[0].portfolios == result.staged.normalized.steps[0].portfolios


def test_explicit_continuation_replays_lookup_and_retains_selected_classifier(monkeypatch):
    calls, _ = recorded_client(monkeypatch, "ztf")
    first = execute_dsl("objects ZTF21abfmbix from ztf via alerce", continue_from=None)
    before = first.to_dict()
    fragment = "with classification from lc_classifier via alerce"
    assert validate_dsl(fragment, continue_from=first).is_runnable
    second = execute_dsl(fragment, continue_from=first)
    assert [name for name, *_ in calls] == ["query_object", "query_probabilities"]
    assert {record.semantic_type for record in classification_records(second.portfolios)} == {"classification@lc_classifier:alerce"}
    assert first.to_dict() == before
    filtered = execute_dsl("filter exists classification@lc_classifier", continue_from=second)
    assert len(filtered.portfolios) == 1
    assert {record.semantic_type for record in classification_records(filtered.portfolios)} == {"classification@lc_classifier:alerce"}
    assert len(calls) == 2


@pytest.mark.parametrize("change", ["ambiguous", "unbound"])
def test_public_validation_rejects_deterministic_planning_defects_before_transport(monkeypatch, change):
    calls, _ = recorded_client(monkeypatch, "ztf")
    graph = build_capability_graph()
    recipes = list(graph.recipe_capabilities)
    original = next(recipe for recipe in recipes if (recipe.broker, recipe.origin, recipe.op) == ("alerce", "ztf", "get_classification"))
    if change == "ambiguous":
        recipes.append(replace(original, alternative_index=1))
    else:
        call, = original.calls
        recipes[recipes.index(original)] = replace(original, calls=(replace(call, params=()),))
    graph = replace(graph, recipe_capabilities=tuple(recipes))
    source = "objects ZTF21abfmbix from ztf via alerce\nwith classification via alerce"
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_valid
    assert not validation.is_runnable
    assert validation.lowering_error is not None
    assert calls == []
    if change == "ambiguous":
        assert validation.lowering_error.code == "planning_error"
        assert "ambiguous" in str(validation.lowering_error)
        from alertissimo.dsl import lower_surface, parse_surface_script
        with pytest.raises(PlanningAmbiguityError):
            plan_workflow(lower_surface(parse_surface_script(source)).workflow, graph)


@pytest.mark.parametrize("origin", ["ztf", "lsst"])
def test_probability_contract_parameters_match_inspected_official_public_signature(origin):
    contract = json.loads((FIXTURES / "probabilities_contract.json").read_text())
    endpoint = EndpointRegistry().resolve("alerce", origin, "query_probabilities")
    assert set(endpoint.params) | set(endpoint.fixed_params) == set(contract["parameters"])
    assert "classifier" not in endpoint.params
