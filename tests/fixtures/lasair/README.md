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
| ZTF | object, lightcurves | `ztf/object_ZTF17aaabasp.json`, `ztf/lightcurves_ZTF17aaabasp.json` | maintainer capture | Supplied 27 November 2026; both contain the same 688 `forcedphot` rows and 1,404 ordinary candidates. Original bytes retained. No history-completeness claim. |
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

## ZTF17aaabasp forced-photometry field evidence

The two saved `forcedphot` arrays are identical. Their `objectid`, `jd`, `fid`,
`forcediffimflux`, `forcediffimfluxunc` and `magzpsci` map into the lightcurve's
separate forced-point array. The generic unit-neutral `flux`/`flux.error` paths
retain instrumental DN; `psf.flux` declares nJy and is not used. The zero point
stays in `calibration.<filter>.zero_point` (mag); no magnitudes or limits are derived.

All 688 epochs are retained. In these captures 256 rows have `-99999` flux/error
sentinels, which map to unavailable values using existing `value_map` and
`skip_null` options. Their epoch, object identity and calibration remain. The
278 nonsentinel negative fluxes keep their sign. This is sentinel handling, not a
signal-to-noise or quality cut. `ranr`/`decnr` remain explicit mapping debt: they
locate the nearest reference-image source, not the forced-photometry target.

Primary field definitions and sentinel evidence:

- [ZTF fp_hist schema](https://zwickytransientfacility.github.io/ztf-avro-alert/schema.html#ztfalertfp-hist): DN flux/error, magnitude zero point, and nearest-reference-source coordinates.
- [ZTF forced-photometry user guide](https://web.ipac.caltech.edu/staff/fmasci/ztf/zfps_userguide.pdf), section 4: `-99999` means photometry could not be computed.

Both endpoint occurrences remain attributable evidence. Asking for the series
through both object lookup and lightcurve acquisition can leave two matching
products; collection predicates then retain `ambiguous_product`, without pooling
or choosing an occurrence. Use the already supplied lookup material, or request
Lasair lightcurve material after an identity-only lookup through another broker.
