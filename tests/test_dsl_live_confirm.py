from scripts.live_dsl_confirm import (
    DEFAULT_DEC,
    DEFAULT_QUORUM,
    DEFAULT_RA,
    DEFAULT_RADIUS_ARCSEC,
    assert_plan_contract,
    compile_and_plan,
)


def test_live_confirm_script_compile_and_plan_contract_without_provider_io():
    _dsl, workflow, run = compile_and_plan(
        ra=DEFAULT_RA,
        dec=DEFAULT_DEC,
        radius_arcsec=DEFAULT_RADIUS_ARCSEC,
        quorum=DEFAULT_QUORUM,
    )

    assert_plan_contract(workflow, run)
