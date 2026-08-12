from pathlib import Path

import pytest

from alertissimo.data_layer.semantic_model import SemanticPathModel


def test_projection_reference_flattens_ordinary_container_contents():
    model = SemanticPathModel.from_ontology()

    assert model.is_valid(
        "detection@lsst:test.forced_photometry.g.psf.flux"
    )
    assert not model.is_valid(
        "detection@lsst:test.forced_photometry.photometry.g.psf.flux"
    )


def test_declared_internal_trait_is_still_flattened():
    model = SemanticPathModel.from_ontology()

    assert model.is_valid("classification@sherlock:lasair.best.description")
    assert not model.is_valid(
        "classification@sherlock:lasair.best._classification_core.description"
    )


@pytest.mark.parametrize(
    "semantic_path",
    [
        "classification@fink.best.class",
        "classification@fink:lasair.best.class",
        "classification@sherlock:lasair.best.description",
    ],
)
def test_valid_record_qualifiers(semantic_path):
    model = SemanticPathModel.from_ontology()

    assert model.is_valid(semantic_path)


@pytest.mark.parametrize(
    "semantic_path",
    [
        "classification@fink@lasair.best.class",
        "classification@@fink.best.class",
        "classification@:lasair.best.class",
        "classification@fink:.best.class",
        "classification@fink:lasair:api.best.class",
    ],
)
def test_invalid_record_qualifiers(semantic_path):
    model = SemanticPathModel.from_ontology()

    assert not model.is_valid(semantic_path)


@pytest.mark.parametrize(
    "semantic_path",
    [
        "detection@lsst:test.photometry.g.mag",
        "detection@lsst:test.photometry.g.mag.error",
        "summary@antares.photometry.i.mag.mean",
        "summary@antares.photometry.i.mag.half_amplitude",
        "summary@antares.photometry.i.flux.chi2",
        "detection@lsst:test.photometry.g.psf.flux",
        "detection@lsst:test.photometry.g.psf.flux.error",
        "summary@lsst:test.photometry.g.psf.flux.mean",
        "summary@lsst:test.photometry.g.psf.flux.mean_error",
        "summary@lsst:test.photometry.g.psf.flux.error_mean",
        "detection@lsst:test.photometry.g.psf.mag",
        "detection@lsst:test.photometry.g.psf.mag.error",
        "detection@lsst:test.photometry.g.aperture.mag",
        "detection@lsst:test.photometry.g.aperture.mag.error",
    ],
)
def test_photometric_quantities_and_their_children_are_materializable(semantic_path):
    model = SemanticPathModel.from_ontology()

    assert model.is_valid(semantic_path)


@pytest.mark.parametrize(
    "relative_path",
    [
        "forced_photometry.g.mag",
        "forced_photometry.g.mag.error",
        "forced_photometry.g.mag.corrected",
        "forced_photometry.g.mag.corrected.error",
        "forced_photometry.g.mag.corrected.extended_component_error",
        "photometry.g.psf.mag.corrected",
        "photometry.g.psf.mag.corrected.error",
        "photometry.g.psf.mag.corrected.extended_component_error",
    ],
)
def test_corrected_magnitude_paths_are_materializable(relative_path):
    model = SemanticPathModel.from_ontology()

    assert model.is_valid(f"detection@ztf:alerce.{relative_path}")


@pytest.mark.parametrize(
    "relative_path",
    [
        "forced_photometry.g.forced_magnitude",
        "forced_photometry.g.forced_magnitude_error",
        "forced_photometry.g.forced_magnitude_corrected",
        "forced_photometry.g.forced_magnitude_corrected_error",
        "forced_photometry.g.forced_magnitude_corrected_extended_error",
    ],
)
def test_provider_shaped_forced_magnitude_paths_are_invalid(relative_path):
    model = SemanticPathModel.from_ontology()

    assert not model.is_valid(f"detection@ztf:alerce.{relative_path}")


def test_generic_photometric_flux_is_materializable_and_unit_neutral():
    model = SemanticPathModel.from_ontology()

    assert model.is_valid("detection@lsst:test.photometry.g.flux")
    assert model.is_valid("detection@lsst:test.photometry.g.flux.error")

    ontology_path = (
        Path(__file__).parents[1]
        / "alertissimo"
        / "data_layer"
        / "semantic_model"
        / "ontology.yaml"
    )
    ontology = ontology_path.read_text(encoding="utf-8")
    generic_flux = ontology.split("    [flux]:", 1)[1].split(
        "    [mag_minus_psf]:", 1
    )[0]

    assert "      unit:" not in generic_flux


@pytest.mark.parametrize(
    "relative_path",
    [
        "photometry.g.mag_error",
        "photometry.g.flux_error",
        "photometry.g.magnitude.mean",
        "photometry.g.magnitude.half_amplitude",
        "photometry.g.magnitude_rate",
        "photometry.g.magnitude_rate_error",
        "photometry.g.psf.mag_error",
        "photometry.g.psf.flux_error",
        "photometry.g.psf.mean",
        "photometry.g.psf.mean_error",
        "photometry.g.psf.flux_error_mean",
        "photometry.g.aperture.mag_error",
        "photometry.g.aperture.flux_error",
        "photometry.g.aperture.large.mag_error",
    ],
)
def test_obsolete_photometry_paths_are_invalid(relative_path):
    model = SemanticPathModel.from_ontology()

    assert not model.is_valid(f"detection@lsst:test.{relative_path}")
    assert not model.is_valid(f"summary@antares.{relative_path}")
