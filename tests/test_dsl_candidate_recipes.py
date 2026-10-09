"""DSL candidates use the same recipe evidence and diagnostics as canonical IR."""

import shutil

import pytest
import yaml

from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import (
    SurfaceCapabilityStatus, SurfaceLoweringError, compile_surface_to_ir,
    lower_surface, parse_surface_script, validate_surface_capabilities,
)
from alertissimo.orchestration.planner import plan_step
from alertissimo.orchestration.validation import validate_step_capabilities


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


@pytest.mark.parametrize("source, status", [
    ("objects from lsst via alerce\n", "supported"),
    ("objects from lsst\n", "supported"),
    ("objects from ztf via alerce\nlatest 1\n", "supported"),
    ("objects from lsst via alerce\nlatest 1\n", "deferred"),
    ("objects from lsst, ztf via alerce\nlatest 1\n", "deferred"),
    ("objects from lsst via alerce\nwithin 1d\n", "deferred"),
    ("objects from lsst via fink\n", "deferred"),
    ("objects from ztf via antares\n", "deferred"),
    ("objects from lsst, ztf via antares\n", "deferred"),
    ("objects from ztf via lasair\n", "unsupported"),
    ("objects from lsst via fink\ninside (34, 33, 3arcsec)\n", "supported"),
    ("objects 1, 2 from lsst via alerce\n", "supported"),
    ("alert 123456 from ztf via fink\n", "unsupported"),
])
def test_public_candidate_validation_matches_the_lowered_operation(graph, source, status):
    surface = parse_surface_script(source)
    step = lower_surface(surface).workflow.steps[0]
    ir_result = validate_step_capabilities(step, graph)
    report = validate_surface_capabilities(surface, graph=graph)
    checks = tuple(check for check in report.checks if check.subject == "candidates")
    assert ir_result.status == report.status.value == status
    assert len(checks) == len(ir_result.source_results)
    for check, result in zip(checks, ir_result.source_results):
        assert check.status.value == result.status
        assert check.reason == result.reason
        assert (check.broker, check.origin) == (result.source.broker, result.source.origin)
        assert check.semantic_noun == ir_result.semantic_type
        assert {endpoint for evidence in check.evidence for endpoint in evidence.endpoints} == {
            endpoint.endpoint for endpoint in result.candidates
        }
    if status == "supported":
        workflow = compile_surface_to_ir(surface, graph=graph)
        assert workflow.steps[0] == step
        assert plan_step(workflow.steps[0], graph)
    else:
        with pytest.raises(SurfaceLoweringError) as raised:
            compile_surface_to_ir(surface, graph=graph)
        assert raised.value.code == f"{status}_capability"
        assert checks[0].reason in str(raised.value)


def local_provider(tmp_path):
    root = tmp_path / "providers"
    destination = root / "alerce" / "lsst"
    shutil.copytree(PROVIDERS_ROOT / "alerce" / "lsst", destination)
    return root, destination


def edit_yaml(path, update):
    doc = yaml.safe_load(path.read_text())
    update(doc)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


@pytest.mark.parametrize("source, endpoint", [
    ("objects from lsst via alerce\n", "query_objects"),
    ("objects from lsst via alerce\ninside (34, 33, 3arcsec)\n", "query_objects"),
    ("objects 1, 2 from lsst via alerce\n", "query_object"),
])
def test_candidate_recipes_work_after_removal_of_operation_tags(tmp_path, source, endpoint):
    root, destination = local_provider(tmp_path)
    def remove_tags(doc):
        for declaration in doc["endpoints"].values():
            declaration["operation_types"] = []
    edit_yaml(destination / "endpoints.yaml", remove_tags)
    graph = build_capability_graph(root)
    surface = parse_surface_script(source)
    report = validate_surface_capabilities(surface, graph=graph)
    assert report.status is SurfaceCapabilityStatus.SUPPORTED
    candidate, = report.checks
    assert candidate.evidence[0].endpoints == (endpoint,)
    step = compile_surface_to_ir(surface, graph=graph).steps[0]
    assert plan_step(step, graph)[0].endpoint == endpoint


@pytest.mark.parametrize("operation, source, status, diagnostic", [
    ("lookup", "objects 1 from lsst via alerce\n", "deferred", "does not bind the target identities"),
    ("cone_search", "objects from lsst via alerce\ninside (34, 33, 3arcsec)\n", "deferred", "canonical cone coordinates"),
    ("semantic_search", "objects from lsst via alerce\n", "unsupported", "no semantic search recipe"),
])
def test_invalid_owned_candidate_recipe_cannot_fall_back_to_legacy_evidence(
    tmp_path, operation, source, status, diagnostic,
):
    root, destination = local_provider(tmp_path)
    def invalid(doc):
        call = doc["recipes"][operation][0]["calls"][0]
        if operation == "lookup":
            call["params"]["oid"] = {"value": 123}
        elif operation == "cone_search":
            call["params"] = {name: {"value": 1} for name in ("ra", "dec", "radius")}
        else:
            call.update(endpoint="query_lightcurve", params={"oid": {"value": 123}})
    edit_yaml(destination / "capabilities.yaml", invalid)
    graph = build_capability_graph(root)
    surface = parse_surface_script(source)
    report = validate_surface_capabilities(surface, graph=graph)
    candidate, = report.checks
    assert candidate.status.value == status
    assert diagnostic in candidate.reason
    assert not candidate.evidence
    with pytest.raises(SurfaceLoweringError) as raised:
        compile_surface_to_ir(surface, graph=graph)
    assert raised.value.code == f"{status}_capability"


def test_candidate_lowering_failure_is_a_deferred_report_with_clause_location(graph):
    surface = parse_surface_script("objects from lsst via alerce\ninside (34, 33, 3)\n")
    report = validate_surface_capabilities(surface, graph=graph)
    candidate, = report.checks
    assert candidate.status is SurfaceCapabilityStatus.DEFERRED
    assert candidate.clause_index == 0
    assert "explicit deg, arcmin, or arcsec unit" in candidate.reason
