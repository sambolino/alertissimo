"""Container $is is transitive membership, separate from field composition."""

import pytest

from alertissimo.data_layer.semantic_model import SemanticPathModel


def model(tmp_path, declarations):
    path = tmp_path / "ontology.yaml"
    path.write_text(declarations)
    return SemanticPathModel.from_ontology(path)


def test_abstract_family_admits_concrete_transitive_descendants(tmp_path):
    paths = model(tmp_path, """<enrichment>:
  abstract: true
  [family_only]:
<product>:
  $is: <enrichment>
  [uri]:
<image>:
  $is: <product>
  [pixels]:
<portfolio>:
  $refs: <enrichment>@{producer}:{channel}
""")
    assert paths.record_types == {"enrichment", "product", "image"}
    assert paths.concrete_record_types == {"product", "image"}
    assert paths.descendants("enrichment") == ("image", "product")
    assert paths.is_a("image", "enrichment")
    assert not paths.is_a("missing", "missing")
    assert paths.is_valid("image@test.pixels")
    assert paths.is_valid("product@test.uri")
    assert not paths.is_valid("image@test.enrichment.pixels")
    assert not paths.is_valid("image@test.uri")  # Membership does not copy fields.
    assert not paths.is_valid("image@test.family_only")
    assert not paths.is_valid("enrichment@test.family_only")


@pytest.mark.parametrize("declarations,reason", [
    ("<a>:\n  $is: <missing>\n", "unknown"),
    ("<a>:\n  $is: <a>\n", "cyclic"),
    ("<a>:\n  $is: <b>\n<b>:\n  $is: <a>\n", "cyclic"),
])
def test_invalid_family_declarations_fail_explicitly(tmp_path, declarations, reason):
    with pytest.raises(ValueError, match=reason):
        model(tmp_path, declarations)


def test_production_family_keeps_concrete_paths_and_measurement_content():
    paths = SemanticPathModel.from_ontology()
    assert paths.descendants("enrichment") == (
        "classification", "color_color", "color_magnitude", "crossmatch",
        "data_product", "lightcurve", "spectrum",
    )
    assert paths.is_valid("measurement@ztf:fink.photometry.g.psf.flux")
    assert paths.is_valid("measurement@ztf:fink.forced_photometry.g.psf.flux")
    assert paths.is_valid("summary@ztf:fink.photometry.g.psf.flux.mean")
    assert paths.is_valid("spectrum@gemini:archive.data_product.format")
    assert not paths.is_valid("detection@ztf:fink.photometry.g.psf.flux")
    assert not paths.is_valid("enrichment@ztf:fink.lightcurve.points")
