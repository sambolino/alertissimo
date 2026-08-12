# Authoritative ANTARES/ZTF 1.14.0 fixtures

These frozen JSON files preserve bytes captured from `antares-client==1.14.0`. They are evidence, not mutable examples. The Alert objects are the authoritative observation history: 316 Alerts produce 316 `detection@ztf:antares` records (70 candidates and 246 upper limits). The 280-row `lightcurve.json` is a strict subset of those Alert IDs and is only a secondary representation; no selection rule for its missing 36 Alert IDs is inferred.

## Alert leaf accounting

The fixture-driven audit in `tests/test_antares_ztf_authoritative_payloads.py` accounts for the union of scalar paths across all 316 Alert rows:

- Observed: **117**
- Mapped: **36**
- Intentionally unmapped: **81**
- Unaccounted: **0**

The mapped total includes Alert identity/time, strict ANTARES passband and candidate/upper-limit semantics, established ZTF quality/reference fields, and the converged aperture, exposure, calibration, reference-image, provenance, and quality-version fields. Remaining debt is explicit in `unmapped_fields.yaml`; it consists of broker transport/derived metadata, redundant aliases, or ZTF quantities for which this ontology does not establish the same meaning.

The raw aliases `ztf_magpsf`, `ztf_sigmapsf`, `ztf_ra`, `ztf_dec`, and `ztf_diffmaglim` are intentionally not emitted a second time because `ant_mag`, `ant_magerr`, `ant_ra`, `ant_dec`, and `ant_maglim` carry the identical values. `ztf_fid` duplicates the strict `ant_passband` binder, while `ztf_candid` is redundant with the complete top-level ANTARES `alert_id`.

## Secondary lightcurve accounting

The test reads all 280 frozen rows, computes their observed column union, and compares it mechanically with the `lightcurve_secondary#...` debt entries:

- Observed: **14**
- Mapped: **0**
- Intentionally unmapped as secondary/duplicate representation: **14**
- Delegated: **0**
- Unaccounted: **0**
- Semantic records produced: **0**

The explicitly accounted columns are `time`, `alert_id`, `ant_mjd`, `ant_survey`, `ant_ra`, `ant_dec`, `ant_passband`, `ant_mag`, `ant_magerr`, `ant_maglim`, `ant_mag_corrected`, `ant_magerr_corrected`, `ant_magulim_corrected`, and `ant_magllim_corrected`.
