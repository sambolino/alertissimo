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
