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
