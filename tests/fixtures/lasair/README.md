# Lasair payload fixture provenance

These fixtures are evidence records, not payloads reverse-engineered from the
registry. Completeness reports must only use rows marked **authoritative**.

| origin | endpoint | fixture | source | captured/documented date | notes |
|---|---|---|---|---|---|
| ZTF | `cone` (`nearest`/`all`) | `ztf/cone.json` | Official Lasair REST API documentation, current/main `cone` example | accessed 2026-08-11 | **Authoritative documented shape**: `object`, `separation`; separation is arcsec from query position. |
| ZTF | `cone` (`count`) | `ztf/cone_count.json` | Official Lasair REST API documentation, current/main request-type contract | accessed 2026-08-11 | **Authoritative documented shape**; maintained separately because it is an aggregate response. |

## Coverage status and API versions

The ZTF registry intentionally spans two documented API generations. The
current/main documentation supplies singular `object` and `sherlock_object`
methods. The develop documentation additionally supplies plural `objects`,
`lightcurves`, and `sherlock_objects`. Endpoint declarations have not been
changed merely to reconcile those branches.

No LSST fixture is currently claimed as complete. In particular, a ZTF object
identifier in a nominal LSST response is not acceptable evidence. LSST
`object`, `cone`, `query`, `sherlock_object`, and `sherlock_position` remain
provisional until an LSST-native saved response, official schema/example, or
authoritative source/test establishes each raw shape. Tests must not turn
invented LSST payloads into a zero-unaccounted completeness claim.

The full documented `ZTF23aabplmy` object and the user-supplied rich
`ZTF20acpwljl` Sherlock response are intentionally not approximated here: the
source payload bytes were unavailable in this checkout, and manufacturing
their values would violate the fixture policy above.
