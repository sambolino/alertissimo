"""Presentation helpers for Alertissimo semantic portfolios."""

import importlib

from .portfolio_html import portfolio_to_html, write_portfolio_html


_LAZY_LIGHTCURVE_EXPORTS = (
    "DEFAULT_TIME_FIELD_PATHS",
    "LIGHTCURVE_COLUMNS",
    "portfolio_lightcurve_dataframe",
    "select_mjd",
    "serialized_portfolio_lightcurve_dataframe",
)


def __getattr__(name: str):
    if name not in _LAZY_LIGHTCURVE_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = importlib.import_module(".portfolio_lightcurve", __name__)
    for export in _LAZY_LIGHTCURVE_EXPORTS:
        globals()[export] = getattr(module, export)
    return globals()[name]


__all__ = [
    "DEFAULT_TIME_FIELD_PATHS",
    "LIGHTCURVE_COLUMNS",
    "portfolio_lightcurve_dataframe",
    "portfolio_to_html",
    "select_mjd",
    "serialized_portfolio_lightcurve_dataframe",
    "write_portfolio_html",
]
