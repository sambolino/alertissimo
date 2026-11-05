"""Ontology family requests expand to existing admitted broker retrievals."""

from dataclasses import replace

import pytest

from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.data_layer.semantic_model import SemanticPathModel
from alertissimo.dsl import (
    SurfaceLoweringError, compile_surface_fragment, compile_surface_to_ir,
    parse_surface_fragment, parse_surface_script, validate_surface_capabilities,
    validate_surface_semantics,
)


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


def source(broker="fink", origin="ztf", tail="with enrichment"):
    return parse_surface_script(f"objects X from {origin} via {broker}\n{tail}\n")


@pytest.mark.parametrize("broker,expected", [
    ("fink", {"get_classification", "get_crossmatch", "get_data_product", "get_lightcurve"}),
    ("alerce", {"get_classification", "get_lightcurve"}),
    ("lasair", {"get_classification", "get_crossmatch", "get_lightcurve"}),
    ("antares", {"get_crossmatch", "get_lightcurve"}),
])
def test_family_expands_to_supported_concrete_gets(graph, broker, expected):
    surface = source(broker)
    assert validate_surface_semantics(surface).is_valid
    report = validate_surface_capabilities(surface, graph=graph)
    assert report.is_supported
    check, = [item for item in report.checks if item.subject == "requirement"]
    assert check.semantic_noun == "enrichment"
    workflow = compile_surface_to_ir(surface, graph=graph)
    assert {step.op for step in workflow.steps[1:]} == expected
    assert all(step.sources[0].broker == broker for step in workflow.steps[1:])
    assert not any(step.op.startswith("color_") for step in workflow.steps)


def test_expansion_uses_supplied_graph_not_default_registry(graph):
    # Remove all product capabilities. Mapped product fields alone cannot admit
    # a retrieval, and the default graph must not reintroduce it during lowering.
    restricted = replace(graph,
        recipe_capabilities=tuple(item for item in graph.recipe_capabilities
                                  if item.op not in {"get_data_product", "get_cutout"}),
        endpoint_capabilities=tuple(item for item in graph.endpoint_capabilities
                                    if not item.endpoint.startswith("cutouts")),
    )
    workflow = compile_surface_to_ir(source(), graph=restricted)
    assert "get_data_product" not in {step.op for step in workflow.steps}


def test_broker_override_and_origin_specific_availability(graph):
    surface = parse_surface_script(
        "objects from ztf, lsst via alerce\nwith enrichment via fink\n"
    )
    workflow = compile_surface_to_ir(surface, graph=graph)
    product, = [step for step in workflow.steps if step.op == "get_data_product"]
    assert [(item.broker, item.origin) for item in product.sources] == [("fink", "ztf")]
    lightcurve, = [step for step in workflow.steps if step.op == "get_lightcurve"]
    assert [(item.broker, item.origin) for item in lightcurve.sources] == [
        ("fink", "ztf"), ("fink", "lsst"),
    ]


def test_family_and_explicit_requirement_do_not_duplicate_retrievals(graph):
    surface = source(tail="with enrichment\nwith lightcurve via fink\nwith enrichment")
    workflow = compile_surface_to_ir(surface, graph=graph)
    assert [step.op for step in workflow.steps].count("get_lightcurve") == 1


def test_family_continuation_preserves_ir_and_deduplicates_existing_gets(graph):
    base = compile_surface_to_ir(source(tail="with lightcurve"), graph=graph)
    fragment = parse_surface_fragment("with enrichment via fink")
    extended = compile_surface_fragment(fragment, base, graph=graph).workflow
    assert extended.steps[:len(base.steps)] == base.steps
    assert [step.op for step in extended.steps].count("get_lightcurve") == 1
    assert {step.op for step in extended.steps} == {
        "lookup", "get_classification", "get_crossmatch", "get_data_product", "get_lightcurve",
    }


@pytest.mark.parametrize("tail", [
    'with enrichment where type = "cutout"',
    "with enrichment from ztf",
    "with enrichment using custom",
])
def test_family_does_not_silently_drop_constraints(graph, tail):
    with pytest.raises(SurfaceLoweringError):
        compile_surface_to_ir(source(tail=tail), graph=graph)


def test_family_without_available_retrievals_is_not_vacuous_success(graph):
    empty = replace(graph, endpoint_capabilities=(), recipe_capabilities=())
    report = validate_surface_capabilities(source(), graph=empty)
    family, = [item for item in report.checks if item.semantic_noun == "enrichment"]
    assert family.status.value == "unsupported"


def test_enum_values_and_substructures_do_not_become_dsl_nouns():
    for noun in ("cutout", "fits", "science", "photometry", "forced_photometry", "detection"):
        assert not validate_surface_semantics(source(tail=f"with {noun}")).is_valid
    assert validate_surface_semantics(source(tail="with measurement")).is_valid
    assert not validate_surface_semantics(source(tail="filter exists enrichment")).is_valid


def test_family_membership_controls_expansion_without_a_dsl_noun_list(graph, tmp_path):
    from alertissimo.data_layer.paths import ONTOLOGY_PATH

    text = ONTOLOGY_PATH.read_text().replace(
        "<lightcurve>:\n  $is: <enrichment>\n", "<lightcurve>:\n"
    )
    path = tmp_path / "ontology.yaml"
    path.write_text(text)
    model = SemanticPathModel.from_ontology(path)
    assert "lightcurve" not in model.record_types
    workflow = compile_surface_to_ir(source(), graph=graph, semantic_paths=model)
    assert "get_lightcurve" not in {step.op for step in workflow.steps}


def test_abstract_family_name_is_not_hardcoded_in_the_dsl(graph, tmp_path):
    from alertissimo.data_layer.paths import ONTOLOGY_PATH

    path = tmp_path / "ontology.yaml"
    path.write_text(ONTOLOGY_PATH.read_text().replace("<enrichment>", "<extras>"))
    model = SemanticPathModel.from_ontology(path)
    workflow = compile_surface_to_ir(source(tail="with extras"), graph=graph, semantic_paths=model)
    assert {step.op for step in workflow.steps[1:]} == {
        "get_classification", "get_crossmatch", "get_data_product", "get_lightcurve",
    }
