from alertissimo.data_layer.semantic_model import SemanticPathModel


def test_producer_qualifier_accepts_optional_channel():
    model = SemanticPathModel.from_ontology()

    assert model.is_valid("classification@fink.best.class")
    assert model.is_valid("classification@fink:some_channel.best.class")
    assert model.is_valid("classification@sherlock:lasair.best.description")
    assert model.is_valid("crossmatch@sdss:lasair.distance.estimate.best.value")


def test_first_level_record_type_is_ontology_derived():
    model = SemanticPathModel.from_ontology()

    assert not model.is_valid("position@ztf:lasair.ra")
    assert not model.is_valid("photometry@ztf:lasair.g.mag")
    assert not model.is_valid("portfolio@alertissimo.summary.identity.object_id")


def test_empty_or_ambiguous_provider_qualifiers_are_rejected():
    model = SemanticPathModel.from_ontology()

    assert not model.is_valid("classification@.best.class")
    assert not model.is_valid("classification@:lasair.best.class")
    assert not model.is_valid("classification@fink:.best.class")
    assert not model.is_valid("classification@fink:lasair:api.best.class")


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
