"""Collection structure is retained without changing existing scalar paths."""

import pytest

from alertissimo.data_layer.semantic_model import SemanticPathModel


@pytest.fixture(scope="module")
def paths():
    return SemanticPathModel.from_ontology()


@pytest.mark.parametrize("collection,leaf", [
    ("points", "photometry.{filter}.psf.mag"),
    ("forced_photometry_points", "forced_photometry.{filter}.psf.flux"),
    ("magnitude_rate_points", "time.mjd"),
    ("color_points", "time.mjd"),
    ("feature_vector_points", "time.mjd"),
])
def test_real_lightcurve_arrays_keep_their_element_roots(paths, collection, leaf):
    prefix = f"lightcurve@ztf:fink.{collection}"
    assert paths.array_boundaries(f"{prefix}.{leaf}") == (prefix,)
    assert paths.is_valid_element_path(prefix, leaf)
    assert paths.is_valid(f"{prefix}.{leaf}")
    assert not paths.is_valid_element_path(prefix, f"lightcurve.{collection}.{leaf}")
    assert not paths.is_valid_element_path(prefix, f"measurement@ztf:fink.{leaf}")
    assert not paths.is_valid_element_path(prefix, "")


def test_scalar_and_unknown_paths_are_not_arrays(paths):
    assert paths.array_boundaries("measurement@ztf:fink.time.mjd") == ()
    assert paths.array_boundaries("lightcurve@ztf:fink.not_declared") == ()
    assert not paths.is_valid_element_path("lightcurve.time", "mjd")
    assert not paths.is_valid_element_path("lightcurve@@fink.points", "time.mjd")
    assert not paths.is_valid_element_path("lightcurve@:fink.points", "time.mjd")


def test_parameter_scopes_do_not_leak_from_generic_field_fallbacks(paths):
    assert paths.parameter_scopes("classification.assessment.{output}.probability") == (
        ("classification.assessment.{output}", "output"),
    )
    assert paths.parameter_scopes("measurement.forced_photometry.{filter}.psf.mag") == (
        ("measurement.forced_photometry.{filter}", "filter"),
    )
    assert paths.array_boundaries("classification.assessment.{output}.probability") == ()
    assert paths.parameter_domain("classification.assessment.{output}", "ztf") is None


@pytest.mark.parametrize("prefix", [
    "photometry", "measurement.photometry", "summary.photometry",
    "lightcurve.points.photometry", "lightcurve.forced_photometry_points.forced_photometry",
])
def test_referenced_and_projected_domains_retain_the_origin_not_observed_bands(paths, prefix):
    parameter = f"{prefix}.{{filter}}"
    assert paths.parameter_domain(parameter, "ztf") == ("g", "r", "i")
    assert paths.parameter_domain(parameter, "lsst") == ("u", "g", "r", "i", "z", "y")
    assert paths.parameter_domain(parameter, "unrecognized") is None


def test_ordered_reader_keeps_repeated_refs_nested_arrays_and_parameter_scopes(tmp_path):
    source = tmp_path / "ontology.yaml"
    source.write_text("""<one>:
  [first]:
<two>:
  [second]:
<sample>:
  <outer>:
    type: array
    items:
      $ref: <_one>
      $ref: <_two>
      <inner>:
        type: array
        items:
          <{filter}>:
            domains:
              ztf: [g, r]
            [value]:
  <other>:
    <{filter}>:
      domains:
        ztf: [i]
      [value]:
<portfolio>:
  $refs: <sample>@{producer}:{channel}
""")
    model = SemanticPathModel.from_ontology(source)
    for leaf in ("first", "second"):
        assert model.is_valid(f"sample@test.outer.{leaf}")
        assert model.is_valid_element_path("sample.outer", leaf)
    assert not model.is_valid("sample@test.outer.items.first")
    assert model.array_boundaries("sample.outer.inner.{filter}.value") == (
        "sample.outer", "sample.outer.inner",
    )
    assert model.parameter_domain("sample.outer.inner.{filter}", "ztf") == ("g", "r")
    assert model.parameter_domain("sample.other.{filter}", "ztf") == ("i",)
    assert model.parameter_scopes("sample.outer.inner.{filter}.value") == (
        ("sample.outer.inner.{filter}", "filter"),
    )


@pytest.mark.parametrize("declaration", [
    "domains:\n    ztf: []", "domains:\n    ztf: [g, g]",
    "domains:\n    ztf: [g,,r]", "domains:\n    ztf: [0]",
    "domains:\n    ztf: g", "domains:\n    ztf: [g]\n    ztf: [r]",
    "domains:",
])
def test_invalid_domain_declarations_are_rejected_at_eof_and_before_next_node(tmp_path, declaration):
    for suffix in ("", "\n<next>:\n  [value]:\n"):
        source = tmp_path / "ontology.yaml"
        source.write_text(f"<{{filter}}>:\n  {declaration}\n{suffix}")
        with pytest.raises(ValueError, match="domains"):
            SemanticPathModel.from_ontology(source)


def test_domain_cannot_be_attached_to_an_ordinary_container(tmp_path):
    source = tmp_path / "ontology.yaml"
    source.write_text("<ordinary>:\n  domains:\n    ztf: [g]\n")
    with pytest.raises(ValueError, match="path parameter"):
        SemanticPathModel.from_ontology(source)
