"""Catalog requirements use targeted recipe evidence, not provider-wide mappings."""

import shutil

import pytest
import yaml

from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import (
    SurfaceCapabilityStatus, SurfaceLoweringError, compile_surface_to_ir,
    lower_surface, parse_surface_script, validate_surface_capabilities,
)
from alertissimo.orchestration.ir import GetCrossmatchStep, Source
from alertissimo.orchestration.validation import validate_step_capabilities


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


@pytest.mark.parametrize("broker, origin, catalog, status", [
    ("antares", "ztf", "gaia", "supported"),
    ("antares", "lsst", "gaia", "supported"),
    ("fink", "ztf", "PANSTARRS", "supported"),
    ("fink", "lsst", "gaia", "supported"),
    ("fink", "ztf", "gaia_dr3", "unsupported"),
    ("lasair", "ztf", "gaia", "deferred"),
    ("alerce", "ztf", "gaia", "unsupported"),
])
def test_catalog_requirement_matches_lowered_retrieval(graph, broker, origin, catalog, status):
    surface = parse_surface_script(
        f"objects from {origin} via {broker}\n"
        "inside (34, 33, 3arcsec)\n"
        f"with crossmatch from {catalog}\n"
    )
    step = lower_surface(surface).workflow.steps[1]
    result = validate_step_capabilities(step, graph)
    report = validate_surface_capabilities(surface, graph=graph)
    check, = (check for check in report.checks if check.subject == "requirement")
    source_result, = result.source_results
    assert check.status.value == result.status == status
    assert check.reason == source_result.reason
    assert (check.origin, check.broker, check.channel) == (origin, broker, broker)
    assert check.producer == catalog.lower()
    assert check.clause_index == 1
    assert check.semantic_noun == "crossmatch"
    assert {name for item in check.evidence for name in item.endpoints} == {
        endpoint.endpoint for endpoint in result.candidates
    }
    if status == "supported":
        assert {item.semantic_record_type for item in check.evidence} == {
            f"crossmatch@{catalog.lower()}:{broker}",
        }
        assert compile_surface_to_ir(surface, graph=graph).steps[1] == step
    else:
        assert check.evidence == ()
        with pytest.raises(SurfaceLoweringError) as caught:
            compile_surface_to_ir(surface, graph=graph)
        assert caught.value.code == f"{status}_capability"
        assert check.reason in str(caught.value)


def test_catalog_broker_override_preserves_all_candidate_origins(graph):
    surface = parse_surface_script(
        "objects from lsst, ztf via alerce\nwith crossmatch from gaia via antares\n"
    )
    report = validate_surface_capabilities(surface, graph=graph)
    checks = tuple(check for check in report.checks if check.subject == "requirement")
    assert [(check.origin, check.broker, check.producer, check.status.value) for check in checks] == [
        ("lsst", "antares", "gaia", "supported"),
        ("ztf", "antares", "gaia", "supported"),
    ]
    assert all(item.semantic_record_type == "crossmatch@gaia:antares" for check in checks for item in check.evidence)


def local_provider(tmp_path):
    root = tmp_path / "providers"
    destination = root / "antares" / "ztf"
    shutil.copytree(PROVIDERS_ROOT / "antares" / "ztf", destination)
    return root, destination


def edit_yaml(path, update):
    document = yaml.safe_load(path.read_text())
    update(document)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def test_supported_catalog_evidence_is_limited_to_eligible_recipe_endpoints(tmp_path):
    root, destination = local_provider(tmp_path)
    def remove_tags(document):
        for endpoint in document["endpoints"].values():
            endpoint["operation_types"] = []
    edit_yaml(destination / "endpoints.yaml", remove_tags)
    def additional_mapping(document):
        # Provider-wide record aggregation now includes a discovery endpoint.
        document["mappings"]["crossmatch@gaia:antares.identity.object_id"].append(
            "cone_loci#catalog_id"
        )
    edit_yaml(destination / "mappings.yaml", additional_mapping)
    graph = build_capability_graph(root)
    record, = (
        item for item in graph.query_records(semantic_record_noun="crossmatch")
        if item.semantic_record_type == "crossmatch@gaia:antares"
    )
    assert "cone_search" in record.endpoints
    surface = parse_surface_script(
        "objects ZTF1 from ztf via antares\nwith crossmatch from gaia\n"
    )
    report = validate_surface_capabilities(surface, graph=graph)
    assert report.status is SurfaceCapabilityStatus.SUPPORTED
    check, = (check for check in report.checks if check.subject == "requirement")
    assert check.evidence[0].semantic_record_type == "crossmatch@gaia:antares"
    assert check.evidence[0].endpoints == ("get_by_ztf_object_id",)
    assert compile_surface_to_ir(surface, graph=graph).steps[1].catalog == "gaia"


def test_owned_catalog_recipe_cannot_fall_back_to_static_mapping(tmp_path):
    root, destination = local_provider(tmp_path)
    def constant_target(document):
        call = document["recipes"]["get_crossmatch"][0]["calls"][0]
        call["params"]["ztf_object_id"] = {"value": "unrelated"}
    edit_yaml(destination / "capabilities.yaml", constant_target)
    graph = build_capability_graph(root)
    surface = parse_surface_script(
        "objects ZTF1 from ztf via antares\nwith crossmatch from gaia\n"
    )
    report = validate_surface_capabilities(surface, graph=graph)
    check, = (check for check in report.checks if check.subject == "requirement")
    assert check.status is SurfaceCapabilityStatus.DEFERRED
    assert "does not bind the target identities" in check.reason
    assert check.evidence == ()
    with pytest.raises(SurfaceLoweringError) as caught:
        compile_surface_to_ir(surface, graph=graph)
    assert caught.value.code == "deferred_capability"


def test_implicit_catalog_requirement_cannot_inherit_another_endpoints_mapping(graph):
    surface = parse_surface_script(
        "objects from ztf via fink\ninside (34, 33, 3arcsec)\n"
        "where exists crossmatch@gaia_dr3.identity.object_id\n"
    )
    report = validate_surface_capabilities(surface, graph=graph)
    check, = (check for check in report.checks if check.subject == "requirement")
    result = validate_step_capabilities(GetCrossmatchStep(
        catalog="gaia_dr3", sources=[Source(broker="fink", origin="ztf")],
    ), graph)
    assert check.status.value == result.status == "unsupported"
    assert check.reason == result.source_results[0].reason
    assert check.producer == "gaia_dr3"
    assert check.clause_index == 1
    assert check.evidence == ()
