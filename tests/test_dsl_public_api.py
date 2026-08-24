from types import SimpleNamespace

import alertissimo.api as api
from scripts import live_dsl_api


VALID_DSL = """\
objects from ztf via alerce
inside (124.87996115142856, -6.0205001, 1arcsec)
latest 1
with lightcurve via fink
"""


def test_validate_dsl_runs_real_static_pipeline_without_provider_execution():
    validation = api.validate_dsl(VALID_DSL, name="UI validation")

    assert validation.is_valid
    assert validation.is_runnable
    assert validation.parse_error is None
    assert validation.lowering_error is None
    assert validation.semantic is not None
    assert validation.semantic.is_valid
    assert validation.capabilities is not None
    assert validation.compilation is not None
    assert [step.op for step in validation.compilation.workflow.steps] == [
        "cone_search",
        "get_lightcurve",
    ]
    assert validation.compilation.workflow.name == "UI validation"


def test_validate_dsl_returns_syntax_failure_as_data():
    validation = api.validate_dsl("objects from ztf via")

    assert not validation.is_valid
    assert not validation.is_runnable
    assert validation.surface is None
    assert validation.semantic is None
    assert validation.capabilities is None
    assert validation.compilation is None
    assert validation.parse_error is not None
    assert validation.lowering_error is None


def test_execute_dsl_composes_existing_pipeline_once(monkeypatch):
    source = "objects from ztf via alerce"
    graph = object()
    registry = object()
    executor = object()
    surface = object()
    workflow = object()
    view = object()
    compilation = SimpleNamespace(workflow=workflow, view=view)
    planned_run = object()
    normalized = object()
    staged = SimpleNamespace(normalized=normalized)
    final_run = object()
    finalized = SimpleNamespace(run=final_run)
    calls = []

    def fake_parse(value):
        calls.append(("parse", value))
        return surface

    def fake_compile(value, **kwargs):
        calls.append(("compile", value, kwargs))
        return compilation

    def fake_plan(value, value_graph):
        calls.append(("plan", value, value_graph))
        return planned_run

    def fake_execute(run, value_registry, value_executor, **kwargs):
        calls.append(("execute", run, value_registry, value_executor, kwargs))
        return staged

    def fake_finalize(value):
        calls.append(("finalize", value))
        return finalized

    monkeypatch.setattr(api, "parse_surface_script", fake_parse)
    monkeypatch.setattr(api, "compile_surface", fake_compile)
    monkeypatch.setattr(api, "plan_workflow", fake_plan)
    monkeypatch.setattr(api, "execute_staged_workflow_run", fake_execute)
    monkeypatch.setattr(api, "finalize_local_semantics", fake_finalize)

    result = api.execute_dsl(
        source,
        name="UI execution",
        graph=graph,
        registry=registry,
        executor=executor,
        validate_semantic_model=False,
    )

    assert calls == [
        ("parse", source),
        (
            "compile",
            surface,
            {
                "graph": graph,
                "name": "UI execution",
            },
        ),
        ("plan", workflow, graph),
        (
            "execute",
            planned_run,
            registry,
            executor,
            {"validate_semantic_model": False},
        ),
        ("finalize", normalized),
    ]
    assert result.source == source
    assert result.surface is surface
    assert result.compilation is compilation
    assert result.workflow is workflow
    assert result.view is view
    assert result.staged is staged
    assert result.result is finalized
    assert result.run is final_run


def test_public_facade_live_script_static_contract_is_offline():
    dsl = live_dsl_api.build_dsl(
        ra=live_dsl_api.DEFAULT_RA,
        dec=live_dsl_api.DEFAULT_DEC,
        radius_arcsec=live_dsl_api.DEFAULT_RADIUS_ARCSEC,
    )
    validation = api.validate_dsl(dsl, name="public facade offline acceptance")

    live_dsl_api.assert_static_contract(validation)

    assert validation.compilation is not None
    assert [step.op for step in validation.compilation.workflow.steps] == [
        "cone_search",
        "get_lightcurve",
    ]
