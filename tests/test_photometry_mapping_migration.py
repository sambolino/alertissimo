"""Regression guard for the PR #111/#112 provider-key migration."""

from pathlib import Path
import re

import yaml

from alertissimo.data_layer.semantic_model import SemanticPathModel


PROVIDERS = Path(__file__).parents[1] / "alertissimo/data_layer/providers"
EXPECTED_REGISTRIES = {
    f"{broker}/{origin}/mappings.yaml"
    for broker in ("alerce", "antares", "fink", "lasair")
    for origin in ("lsst", "ztf")
}
PHOTOMETRY = r"(?:^|\.)(?:forced_)?photometry\.[^.]+"
MAG_STATS = (
    "mean|half_amplitude|maximum_deviation_from_median|"
    "median_absolute_deviation|chi2|excess_kurtosis|eta_e|cusum|"
    "anderson_darling_normal|beyond_1_std|beyond_2_std|maximum_slope|"
    "duration|linear_fit_slope|linear_fit_reduced_chi2"
)
PSF_AGGREGATES = (
    "scatter_chi2|flux_error_mean|linear_intercept|linear_slope|mad|"
    "maximum|maximum_slope|mean|mean_error|minimum|measurement_count|"
    "percentile_05|percentile_25|percentile_50|percentile_75|"
    "percentile_95|sigma|skew|stetson_j"
)
OBSOLETE = re.compile(
    PHOTOMETRY
    + rf"(?:\.(?:mag_error|flux_error|magnitude\.(?:{MAG_STATS})|"
    rf"magnitude_rate(?:_error)?|psf\.(?:mag_error|flux_error|{PSF_AGGREGATES})|"
    r"aperture\.(?:mag_error|flux_error|large\.mag_error)))$"
)
PHASE_2_PATHS = {
    "detection@lsst:fink.reference_image.photometry.{filter}.flux_error",
    "lightcurve@lsst:fink.forced_photometry.{filter}.psf.flux_error",
}
MIGRATED = re.compile(
    PHOTOMETRY
    + rf"(?:\.mag\.(?:error|rate|rate_error|{MAG_STATS})|\.flux\.error|"
    rf"\.psf\.(?:mag\.error|flux\.(?:error|error_mean|{PSF_AGGREGATES.replace('flux_error_mean|', '')}))|"
    r"\.aperture\.(?:mag\.error|flux\.error|large\.mag\.error))$"
)


def test_exact_provider_registries_have_no_obsolete_photometry_mapping_keys():
    registries = {
        path.relative_to(PROVIDERS).as_posix()
        for path in PROVIDERS.glob("*/*/mappings.yaml")
        if path.relative_to(PROVIDERS).parts[0] in {"alerce", "antares", "fink", "lasair"}
    }
    assert registries == EXPECTED_REGISTRIES

    obsolete = []
    migrated = []
    for relative_path in sorted(registries):
        mappings = yaml.safe_load((PROVIDERS / relative_path).read_text())["mappings"]
        obsolete.extend(
            (relative_path, key)
            for key in mappings
            if OBSOLETE.search(key) and key not in PHASE_2_PATHS
        )
        migrated.extend(key for key in mappings if MIGRATED.search(key))

    assert obsolete == []
    model = SemanticPathModel.from_ontology()
    assert migrated
    invalid_migrations = [key for key in migrated if not model.is_valid(key)]
    assert invalid_migrations == []
