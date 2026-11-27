# Lasair fixture provenance

Fixture coverage means that every observed leaf in that saved payload is mapped or
explicitly recorded as semantic debt. It is not, by itself, a claim that every
possible API response field is complete.

| Origin | Endpoint | Fixture | Status | Evidence |
|---|---|---|---|---|
| ZTF | cone | `ztf/cone.json` | authoritative | Documented normal Lasair cone result shape. |
| ZTF | sherlock_position | `ztf/sherlock_position.json` | authoritative | Observed `ZTF20acpwljl` response supplied by the user. |
| ZTF | object | `ztf/object.json` | provisional | Reduced representative payload; no complete official example was available locally. |
| ZTF | object, lightcurves | `ztf/object_ZTF23aamxeqf.json`, `ztf/lightcurves_ZTF23aamxeqf.json` | maintainer capture | Supplied 27 November 2026; each contains 2 candidates with `candid` and 19 limit rows, with empty `forcedphot`. Bytes retained unchanged; no retrieval-completeness claim. |
| ZTF | candidate row | `ztf/object_rich_limit_synthetic.json` | synthetic regression | Rich-format limit: absent `candid`, copied `magpsf == diffmaglim`, plus `json`, `mjd` and `since_now`; not a provider capture. |
| ZTF | objects, lightcurves, query, sherlock_objects | corresponding `ztf/*.json` | provisional | Representative mapping fixtures; query columns are caller-selected. |
| LSST | object | `lsst/object.json` | provisional | Representative synthetic payload, not an observed full API response. |
| LSST | cone | `lsst/cone.json` | provisional | Representative synthetic payload, not an observed full API response. |
| LSST | query | `lsst/query.json` | provisional | Representative caller-selected projection. |
| LSST | sherlock_object | `lsst/sherlock_object.json` | provisional | Representative Sherlock structure; payload provenance is not authoritative. |
| LSST | sherlock_position | `lsst/sherlock_position.json` | provisional | Representative Sherlock structure; payload provenance is not authoritative. |

The authoritative rows above establish completeness only for those observed or
documented response shapes. Provisional fixtures exercise registry behavior without
asserting completeness of the real endpoint payload.

Cone-search count mode is documented, but its exact serialized response shape is
unverified.
