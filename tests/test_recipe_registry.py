"""Contract coverage for inactive provider recipes; no transport invocation."""

import shutil

import pytest
import yaml

from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraphError, build_capability_graph,
)
from alertissimo.data_layer.runtime.recipes import (
    CallValueSource, ConstantValueSource, EncoderValueSource, StepValueSource,
)


def provider(tmp_path, broker="lasair", origin="ztf"):
    root = tmp_path / "providers"
    destination = root / broker / origin
    shutil.copytree(PROVIDERS_ROOT / broker / origin, destination)
    # Each contract test authors its own recipe declaration, independent of
    # which operations have since migrated in the production provider.
    (destination / "capabilities.yaml").unlink(missing_ok=True)
    return root, destination


def write_recipes(destination, recipes):
    (destination / "capabilities.yaml").write_text(yaml.safe_dump({
        "broker": destination.parent.name,
        "origin": destination.name,
        "recipes": recipes,
    }, sort_keys=False), encoding="utf-8")


def cone_call():
    return {"endpoint": "cone", "params": {
        name: {"from": f"step.{name}"} for name in ("ra", "dec", "radius")
    }}


def summary_call():
    return {"endpoint": "query", "required": False, "params": {
        "conditions": {"from": {"call": 0, "path": "summary.identity.object_id"}},
        "selected": {"value": "objects.objectId,objects.ramean"},
        "tables": {"value": "objects"},
        "limit": {"value": 100},
    }}


def test_absent_recipes_preserve_existing_graph(tmp_path):
    root, _ = provider(tmp_path)
    graph = build_capability_graph(root)
    assert graph.recipe_capabilities == ()
    assert graph.query_recipes(op="cone_search") == ()
    assert graph.query_endpoints(broker="lasair", origin="ztf", operation_type="cone_search")


def test_compiles_candidate_dependency_and_keeps_call_output_evidence(tmp_path):
    root, destination = provider(tmp_path)
    before = build_capability_graph(root)
    write_recipes(destination, {"cone_search": [{"calls": [cone_call(), summary_call()]}]})
    graph = build_capability_graph(root)
    recipe, = graph.query_recipes(broker="lasair", origin="ztf", op="cone_search")
    assert graph.endpoint_capabilities == before.endpoint_capabilities
    assert recipe.alternative_index == 0
    cone, summary = recipe.calls
    assert cone.required and not summary.required
    assert {item.relative_field_path for item in cone.outputs} == {"identity.object_id"}
    assert "position.ra" in {item.relative_field_path for item in summary.outputs}
    assert cone.params[0].source == StepValueSource(("ra",))
    params = {item.parameter: item.source for item in summary.params}
    assert params["conditions"] == CallValueSource(0, "summary.identity.object_id")
    assert params["limit"] == ConstantValueSource(100)
    assert graph.query_recipes(broker="fink") == ()
    assert graph.query_recipes(origin="lsst") == ()
    assert graph.query_recipes(op="lookup") == ()


def test_composite_astropy_encoder_is_inspected_without_execution(tmp_path):
    root, destination = provider(tmp_path, "antares")
    write_recipes(destination, {"cone_search": [{"calls": [{
        "endpoint": "cone_search", "params": {
            "center": {"from": {"ra": "step.ra", "dec": "step.dec"}},
            "radius": {"from": "step.radius"},
        },
    }]}]})
    recipe, = build_capability_graph(root).query_recipes(op="cone_search")
    center = recipe.calls[0].params[0].source
    assert isinstance(center, EncoderValueSource)
    assert dict(center.inputs) == {
        "ra": StepValueSource(("ra",)), "dec": StepValueSource(("dec",)),
    }


def test_scalar_and_collection_targets_remain_separate_alternatives(tmp_path):
    root, destination = provider(tmp_path)
    write_recipes(destination, {"lookup": [
        {"calls": [{"endpoint": "object", "params": {"objectId": {"from": "step.target.ids"}}}]},
        {"calls": [{"endpoint": "objects", "params": {"objectIds": {"from": "step.target.ids"}}}]},
    ]})
    recipes = build_capability_graph(root).query_recipes(op="lookup")
    assert [recipe.alternative_index for recipe in recipes] == [0, 1]
    assert all(recipe.calls[0].params[0].source == StepValueSource(("target", "ids")) for recipe in recipes)


@pytest.mark.parametrize("assignment, message", [
    ({"from": "step.missing"}, "unknown IR field"),
    ({"from": "position.ra"}, "direct step field path"),
    ({"from": "step.ra + 1"}, "direct step field path"),
    ({"from": "step.sources.broker"}, "cannot traverse"),
    ({"from": "step.ra", "value": 1}, "exactly one"),
    ({"value": True}, "physical type"),
    ({"from": {"call": 0, "path": "summary.identity.object_id"}}, "earlier call"),
])
def test_rejects_invalid_parameter_sources(tmp_path, assignment, message):
    root, destination = provider(tmp_path)
    call = cone_call()
    call["params"]["ra"] = assignment
    write_recipes(destination, {"cone_search": [{"calls": [call]}]})
    with pytest.raises(CapabilityGraphError, match=message):
        build_capability_graph(root)


@pytest.mark.parametrize("change, message", [
    ("operation", "unknown IR operation"),
    ("endpoint", "unknown endpoint"),
    ("parameter", "unknown parameter"),
    ("missing", "required parameter"),
    ("required", "required must be boolean"),
    ("optional", "required call"),
    ("extra", "unknown keys"),
])
def test_rejects_invalid_recipe_contracts(tmp_path, change, message):
    root, destination = provider(tmp_path)
    call = cone_call()
    recipes = {"cone_search": [{"calls": [call]}]}
    if change == "operation":
        recipes["ConeSearchStep"] = recipes.pop("cone_search")
    elif change == "endpoint":
        call["endpoint"] = "missing"
    elif change == "parameter":
        call["params"]["missing"] = {"value": 1}
    elif change == "missing":
        del call["params"]["radius"]
    elif change == "required":
        call["required"] = "false"
    elif change == "optional":
        call["required"] = False
    else:
        call["condition"] = "$history.missing"
    write_recipes(destination, recipes)
    with pytest.raises(CapabilityGraphError, match=message):
        build_capability_graph(root)


@pytest.mark.parametrize("change, message", [
    ("future", "earlier call"),
    ("field", "only summary.identity.object_id"),
    ("unmapped", "does not map"),
    ("optional", "depends on an optional call"),
])
def test_dependency_requires_owned_identity_and_required_ancestors(tmp_path, change, message):
    root, destination = provider(tmp_path)
    first, second = cone_call(), summary_call()
    if change == "future":
        second["params"]["conditions"]["from"]["call"] = 2
    elif change == "field":
        second["params"]["conditions"]["from"]["path"] = "summary.position.ra"
    elif change == "unmapped":
        first = {"endpoint": "lightcurves", "params": {"objectIds": {"value": "ZTF20acpwljl"}}}
    else:
        first["required"] = False
        second["required"] = True
    write_recipes(destination, {"cone_search": [{"calls": [first, second]}]})
    with pytest.raises(CapabilityGraphError, match=message):
        build_capability_graph(root)


def test_rejects_unknown_encoder_and_wrong_named_operands(tmp_path):
    root, destination = provider(tmp_path, "antares")
    call = {"endpoint": "cone_search", "params": {
        "center": {"from": {"ra": "step.ra"}}, "radius": {"from": "step.radius"},
    }}
    write_recipes(destination, {"cone_search": [{"calls": [call]}]})
    with pytest.raises(CapabilityGraphError, match="match declared operands"):
        build_capability_graph(root)
    call["params"]["center"]["from"]["dec"] = "step.dec"
    write_recipes(destination, {"cone_search": [{"calls": [call]}]})
    path = destination / "endpoints.yaml"
    document = yaml.safe_load(path.read_text())
    document["endpoints"]["cone_search"]["params"]["center"]["binding"]["adapter"] = "invented:adapter"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(CapabilityGraphError, match="registered request transform"):
        build_capability_graph(root)


def test_duplicate_keys_and_orphan_recipe_files_fail_visibly(tmp_path):
    root, destination = provider(tmp_path)
    path = destination / "capabilities.yaml"
    path.write_text("broker: lasair\nbroker: lasair\norigin: ztf\nrecipes: {}\n", encoding="utf-8")
    with pytest.raises(CapabilityGraphError, match="duplicate YAML key"):
        build_capability_graph(root)
    path.unlink()
    orphan = root / "missing" / "ztf"
    orphan.mkdir(parents=True)
    write_recipes(orphan, {})
    with pytest.raises(CapabilityGraphError, match="no normalized provider contracts"):
        build_capability_graph(root)


def test_transport_fixed_values_satisfy_required_params_but_cannot_be_overridden(tmp_path):
    root, destination = provider(tmp_path)
    path = destination / "endpoints.yaml"
    document = yaml.safe_load(path.read_text())
    document["transport_defaults"]["fixed_params"] = {"radius": 10}
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    call = cone_call()
    del call["params"]["radius"]
    write_recipes(destination, {"cone_search": [{"calls": [call]}]})
    assert build_capability_graph(root).query_recipes(op="cone_search")
    call["params"]["radius"] = {"value": 20}
    write_recipes(destination, {"cone_search": [{"calls": [call]}]})
    with pytest.raises(CapabilityGraphError, match="conflicts with fixed parameter"):
        build_capability_graph(root)
