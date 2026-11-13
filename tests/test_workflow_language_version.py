"""New construction and serialized pre-collection IR have distinct defaults."""

import json

import pytest
from pydantic import TypeAdapter, ValidationError

from alertissimo.orchestration.ir import WorkflowIR
from alertissimo.orchestration.ir.models import CURRENT_DSL_VERSION
from alertissimo.orchestration.runtime.models import WorkflowRun


def test_new_ir_defaults_to_current_and_round_trips_without_version_drift():
    workflow = WorkflowIR(steps=[])
    assert workflow.dsl_version == CURRENT_DSL_VERSION == 2
    assert WorkflowIR.model_validate(workflow.model_dump()) == workflow
    assert WorkflowIR.model_validate_json(workflow.model_dump_json()) == workflow
    assert WorkflowIR.model_json_schema()["properties"]["dsl_version"]["default"] == 2


def test_unversioned_ir_loads_as_legacy_without_mutating_the_input():
    legacy = {"steps": []}
    python = WorkflowIR.model_validate(legacy)
    serialized = WorkflowIR.model_validate_json(json.dumps(legacy))
    assert python.dsl_version == serialized.dsl_version == 1
    assert WorkflowIR.model_validate_json(python.model_dump_json()) == python
    assert legacy == {"steps": []}


def test_nested_and_adapter_deserialization_also_use_the_legacy_version():
    raw = {"workflow": {"steps": []}, "steps": []}
    assert WorkflowRun.model_validate(raw).workflow.dsl_version == 1
    assert WorkflowRun.model_validate_json(json.dumps(raw)).workflow.dsl_version == 1
    adapter = TypeAdapter(list[WorkflowIR])
    assert adapter.validate_python([{"steps": []}])[0].dsl_version == 1
    assert adapter.validate_json('[{"steps": []}]')[0].dsl_version == 1
    workflow = WorkflowIR(steps=[])
    assert WorkflowRun(workflow=workflow, steps=()).workflow.dsl_version == 2


@pytest.mark.parametrize("version", [0, -1, True, False, 1.0, "1", None])
def test_version_is_a_positive_integer_without_coercion(version):
    with pytest.raises(ValidationError):
        WorkflowIR(steps=[], dsl_version=version)
    with pytest.raises(ValidationError):
        WorkflowIR.model_validate({"steps": [], "dsl_version": version})


def test_newer_versions_are_refused_on_all_deserialization_paths():
    raw = {"steps": [], "dsl_version": CURRENT_DSL_VERSION + 1}
    for load in (
        lambda: WorkflowIR(**raw),
        lambda: WorkflowIR.model_validate(raw),
        lambda: WorkflowIR.model_validate_json(json.dumps(raw)),
        lambda: WorkflowRun.model_validate({"workflow": raw, "steps": []}),
        lambda: WorkflowRun.model_validate_json(json.dumps({"workflow": raw, "steps": []})),
    ):
        with pytest.raises(ValidationError, match="newer than supported"):
            load()


@pytest.mark.parametrize("version", [1, CURRENT_DSL_VERSION])
def test_scalar_fragment_continuation_preserves_the_existing_ir_version(version):
    from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
    from alertissimo.dsl import compile_surface, compile_surface_fragment, parse_surface_fragment, parse_surface_script

    graph = build_capability_graph()
    base = compile_surface(parse_surface_script(
        "objects from ztf via lasair\ninside (124.879961, -6.020500, 5arcsec)"
    ), graph=graph).workflow
    base = WorkflowIR.model_validate({**base.model_dump(), "dsl_version": version})
    fragment = parse_surface_fragment("with lightcurve via fink")
    extended = compile_surface_fragment(fragment, base, graph=graph).workflow
    assert extended.dsl_version == version
    assert extended.steps[:len(base.steps)] == base.steps
