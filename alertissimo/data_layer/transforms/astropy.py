"""Astropy-backed physical request-value constructors.

Astropy is imported lazily so planning and focused orchestration paths do not
acquire the optional dependency merely by importing Alertissimo's transform layer.
"""

from __future__ import annotations


def skycoord_icrs_degrees(*, ra, dec):
    """Build an ICRS ``SkyCoord`` from canonical decimal-degree coordinates."""

    from astropy import units as u
    from astropy.coordinates import SkyCoord

    return SkyCoord(ra=float(ra) * u.deg, dec=float(dec) * u.deg, frame="icrs")


def angle_arcsec(*, radius):
    """Build an Astropy ``Angle`` from a canonical arcsecond radius."""

    from astropy import units as u
    from astropy.coordinates import Angle

    return Angle(float(radius), unit=u.arcsec)


__all__ = ["angle_arcsec", "skycoord_icrs_degrees"]
