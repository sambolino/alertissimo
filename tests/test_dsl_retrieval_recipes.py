"""DSL retrieval evidence must agree with the operation actually emitted."""

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


@pytest.mark.parametrize("broker, origin, product, status", [
    ("fink", "lsst", "lightcurve", "supported"),
    ("lasair", "lsst", "lightcurve", "supported"),
    ("antares", "ztf", "lightcurve", "supported"),
    ("alerce", "lsst", "lightcurve", "supported"),
    ("fink", "ztf", "data_product", "deferred"),
    ("fink", "lsst", "data_product", "unsupported"),
    ("alerce", "ztf", "data_product", "deferred"),
    ("alerce", "lsst", "data_product", "deferred"),
])
def test_retrieval_report_matches_canonical_ir(graph, broker, origin, product, status):
    surface = parse_surface_script(
        f"objects from {origin} via {broker}\n"
        "inside (34, 33, 3arcsec)\n"
        f"with {product}\n"
    )
    step = lower_surface(surface).workflow.steps[1]
    result = validate_step_capabilities(step, graph)
    report = validate_surface_capabilities(surface, graph=graph)
    requirement, = (check for check in report.checks if check.subject == "requirement")
    source_result, = result.source_results
    assert requirement.status.value == result.status == status
    assert requirement.reason == source_result.reason
    assert (requirement.origin, requirement.broker, requirement.channel) == (origin, broker, broker)
    assert requirement.semantic_noun == product
    assert requirement.clause_index == 1
    assert {name for evidence in requirement.evidence for name in evidence.endpoints} == {
        endpoint.endpoint for endpoint in source_result.candidates
    }
    if status == "supported":
        assert compile_surface_to_ir(surface, graph=graph).steps[1] == step
        assert plan_step(step, graph)
    else:
        with pytest.raises(SurfaceLoweringError) as caught:
            compile_surface_to_ir(surface, graph=graph)
        assert caught.value.code == f"{status}_capability"
        assert requirement.reason in str(caught.value)


def test_retrieval_broker_override_preserves_each_candidate_origin(graph):
    surface = parse_surface_script(
        "objects from lsst, ztf via alerce\nwith lightcurve via lasair\n"
    )
    report = validate_surface_capabilities(surface, graph=graph)
    checks = tuple(check for check in report.checks if check.subject == "requirement")
    result = validate_step_capabilities(lower_surface(surface).workflow.steps[1], graph)
    assert [(check.origin, check.broker, check.status.value) for check in checks] == [
        ("lsst", "lasair", "supported"), ("ztf", "lasair", "supported"),
    ]
    assert [check.reason for check in checks] == [item.reason for item in result.source_results]


def test_cutout_routing_respects_the_supplied_ontology_gate(graph):
    # The current production ontology calls these artifacts data_product.
    # Exercise the existing cutout lowering rule with an ontology-valid test noun.
    class Paths:
        record_types = frozenset({"summary", "cutout"})

        def is_valid(self, path):
            return True

    surface = parse_surface_script("objects ZTF1 from ztf via fink\nwith cutout\n")
    step = lower_surface(surface, semantic_paths=Paths()).workflow.steps[1]
    result = validate_step_capabilities(step, graph)
    report = validate_surface_capabilities(surface, graph=graph, semantic_paths=Paths())
    check, = (check for check in report.checks if check.subject == "requirement")
    assert check.status.value == result.status == "deferred"
    assert check.reason == result.source_results[0].reason
    assert "response shape/mode" in check.reason


def local_provider(tmp_path, broker="alerce", origin="lsst"):
    root = tmp_path / "providers"
    destination = root / broker / origin
    shutil.copytree(PROVIDERS_ROOT / broker / origin, destination)
    return root, destination


def edit_yaml(path, update):
    document = yaml.safe_load(path.read_text())
    update(document)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def test_lightcurve_recipe_support_does_not_need_operation_tags(tmp_path):
    root, destination = local_provider(tmp_path)
    def remove_tags(document):
        for endpoint in document["endpoints"].values():
            endpoint["operation_types"] = []
    edit_yaml(destination / "endpoints.yaml", remove_tags)
    graph = build_capability_graph(root)
    surface = parse_surface_script("objects 1 from lsst via alerce\nwith lightcurve\n")
    report = validate_surface_capabilities(surface, graph=graph)
    assert report.status is SurfaceCapabilityStatus.SUPPORTED
    requirement, = (check for check in report.checks if check.subject == "requirement")
    assert requirement.evidence[0].endpoints == ("query_lightcurve",)
    step = compile_surface_to_ir(surface, graph=graph).steps[1]
    assert plan_step(step, graph)[0].parameter_sources == {"oid": ("target", "ids")}


def test_unbindable_owned_lightcurve_cannot_fall_back_to_tags_or_mapped_records(tmp_path):
    root, destination = local_provider(tmp_path)
    def unbindable(document):
        call = document["recipes"]["get_lightcurve"][0]["calls"][0]
        call["params"]["oid"] = {"value": 123}
    edit_yaml(destination / "capabilities.yaml", unbindable)
    graph = build_capability_graph(root)
    surface = parse_surface_script("objects 1 from lsst via alerce\nwith lightcurve\n")
    report = validate_surface_capabilities(surface, graph=graph)
    requirement, = (check for check in report.checks if check.subject == "requirement")
    assert requirement.status is SurfaceCapabilityStatus.DEFERRED
    assert "does not bind the target identities" in requirement.reason
    assert requirement.evidence == ()
    with pytest.raises(SurfaceLoweringError) as caught:
        compile_surface_to_ir(surface, graph=graph)
    assert caught.value.code == "deferred_capability"


def test_verified_json_product_recipe_support_does_not_need_operation_tags(tmp_path):
    root, destination = local_provider(tmp_path, "fink", "ztf")
    def json_endpoint(document):
        endpoint = document["endpoints"]["cutouts"]
        endpoint["output"] = {"type": "object", "item": "product"}
        endpoint["params"].pop("kind")
        endpoint["params"].pop("output-format")
        for endpoint in document["endpoints"].values():
            endpoint["operation_types"] = []
    edit_yaml(destination / "endpoints.yaml", json_endpoint)
    def json_calls(document):
        for op in ("get_cutout", "get_data_product"):
            params = document["recipes"][op][0]["calls"][0]["params"]
            params.pop("kind")
            params.pop("output-format")
    edit_yaml(destination / "capabilities.yaml", json_calls)
    def json_fields(document):
        document["mappings"]["data_product@ztf:fink.payload"] = ["cutouts#content"]
        document["mappings"]["data_product@ztf:fink.type"] = ["cutouts#type"]
    edit_yaml(destination / "mappings.yaml", json_fields)
    graph = build_capability_graph(root)
    surface = parse_surface_script("objects ZTF1 from ztf via fink\nwith data_product\n")
    report = validate_surface_capabilities(surface, graph=graph)
    assert report.status is SurfaceCapabilityStatus.SUPPORTED
    step = compile_surface_to_ir(surface, graph=graph).steps[1]
    plan, = plan_step(step, graph)
    assert plan.endpoint == "cutouts"
    assert plan.parameter_sources == {"objectId": ("target", "ids")}


@pytest.mark.parametrize("requirement, diagnostic", [
    ("with lightcurve from lsst", "unrepresentable_producer_constraint"),
    ("with data_product science", "unsupported_product_detail"),
])
def test_retrieval_lowering_failure_is_deferred_with_clause_location(graph, requirement, diagnostic):
    surface = parse_surface_script(f"objects 1 from lsst via alerce\n{requirement}\n")
    report = validate_surface_capabilities(surface, graph=graph)
    check, = (check for check in report.checks if check.subject == "requirement")
    assert check.status is SurfaceCapabilityStatus.DEFERRED
    assert check.clause_index == 0
    assert check.producer == ("lsst" if "from" in requirement else None)
    assert diagnostic in check.reason
