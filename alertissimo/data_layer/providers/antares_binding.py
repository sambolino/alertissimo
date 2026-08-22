"""Request-side physical adapters for the ANTARES Python client.

These helpers sit at the provider boundary: orchestration continues to express a
cone as canonical decimal-degree RA/Dec plus an arcsecond radius, while the official
ANTARES client receives the Astropy objects required by its Python API.

Imports stay inside the functions so capability/planning-only paths do not acquire
Astropy as an eager dependency.
"""

from __future__ import annotations


def skycoord_icrs_degrees(*, ra, dec):
    """Build the physical ``SkyCoord`` expected by ANTARES cone search."""

    from astropy import units as u
    from astropy.coordinates import SkyCoord

    return SkyCoord(ra=float(ra) * u.deg, dec=float(dec) * u.deg, frame="icrs")


def angle_arcsec(*, radius):
    """Build the physical ``Angle`` expected by ANTARES cone search."""

    from astropy import units as u
    from astropy.coordinates import Angle

    return Angle(float(radius), unit=u.arcsec)


__all__ = ["angle_arcsec", "skycoord_icrs_degrees"]
