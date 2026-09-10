import pytest

from alertissimo.orchestration.ir import MatchStep
from alertissimo.orchestration.matching import UnsupportedMatchError, match_step_portfolios
from alertissimo.orchestration.normalization import StepPortfolioResult


def test_positional_match_does_not_reuse_temporal_within_keyword():
    step = MatchStep(
        params={
            "candidate_origins": ["lsst", "ztf"],
            "predicate": "position within 1arcsec",
        }
    )

    with pytest.raises(UnsupportedMatchError, match="position inside <angle>"):
        match_step_portfolios(
            step,
            StepPortfolioResult(step_index=0, executions=()),
            step_index=1,
        )
