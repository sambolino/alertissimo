# Provider field coverage and catalogue retrieval

Contract for [implementation item 3](next_functional_work.md#3-catalogue-crossmatches-and-field-coverage).
Maximize broker diversity: catalogues, associations, distances, redshifts, matched-
source classifications, photometry and context. Map every scientifically
established field possible and correct existing mappings, without manufacturing
candidate-classifier parity.

## Existing owners and accounting

All eight provider/survey directories already have `mappings.yaml` and
`unmapped_fields.yaml`. Use
[`tools/audit_payload_mapping_coverage.py`](../tools/audit_payload_mapping_coverage.py),
captures, fixture reports and authoritative-payload regressions. Extend these
rather than add an audit system or runtime registry.

Zero unaccounted leaves is not zero mapping debt. The rich ANTARES/ZTF composite
checked at main `b7f9905` (7 November 2026) has 90 mapped, 812 intentionally unmapped,
712 delegated/structural and zero unaccounted leaf references. These are
fixture-specific accounting categories, not observation counts or all-service
coverage. Revisit intentional debt for the new scientific-coverage objective.

The same capture has 316 authoritative Alerts versus a 280-row secondary client
lightcurve. Preserve the existing authoritative observation route instead of
mapping duplicate representations as additional observations.

## Required audit trail

For every audited field, retain:

| Information | Required content |
|---|---|
| Native source | Broker/survey, endpoint, branch and exact field reference |
| Ownership | Candidate, observation, matched source, host or processing metadata; relevant identities |
| Meaning | Definition, units, time/coordinate convention, null/sentinel behaviour |
| Existing mapping | Destination/transform or absence |
| Disposition | Preserve, correct, add, resolve uncertain meaning, provenance or justified exclusion |
| Evidence | Capture/schema/primary definition and regression/example |

Account for every audited field. Do not claim all native catalogues from a single
capture, or count a generic debt reason as completion. Discuss genuinely missing
scientific concepts instead of forcing them into misleading fields or a blind
extra-field dump. Keep processing/transport metadata in appropriate provenance.

Preserve catalogue/source identity, match multiplicity/rank, scope and uncertainty.
Do not promote catalogue classifications to transient classifications. Distinguish
angular separation, pixel distance and physical distance; preserve the existing
Fink/ZTF pixel-distance correction. A cone radius is not an implicit association
radius. Similar timestamps/positions do not prove duplicate record identity.

## Dated public-request snapshot

Checked through `validate_dsl(..., continue_from=None)` and offline planning after
explicit-ID lookup and unwindowed cone, at main `b7f9905`. This is not live acceptance,
complete field coverage or an exhaustive native catalogue list.

| Pair | Targeted catalogue requests that plan | Remaining distinction/gap |
|---|---|---|
| ALeRCE/ZTF | None | No admitted crossmatch Get/mappings. Investigate verified catalogue/catsHTM inputs, outputs and association/ownership semantics. |
| ALeRCE/LSST | None | Separate Rubin investigation; no inherited ZTF contract. |
| Fink/ZTF | `gaia_dr1`, `mangrove`, `panstarrs`, `simbad`, `tns` | Mapped `gaia_dr3`, `gaia_variability`, `gcvs`, `spicy`, `vsx` are not eligible on the checked targeted route. Mapped `3hsp`/`4lac` names fail lexical admission; backend eligibility is not proved by that rejection. |
| Fink/LSST | `gaia`, `gcvs`, `legacydr8`, `mangrove`, `simbad`, `spicy`, `tns`, `vsx`, `x3hsp`, `x4lac` | Planning does not establish complete mapping or presence for each object. |
| Lasair/ZTF | None in the checked sources | Generic routes are ambiguous; targeted TNS also has object/batch ambiguity. Targeted Gaia has only dynamically unproven producer evidence. |
| Lasair/LSST | `tns` | Generic object/Sherlock ambiguity; Gaia dynamic-producer restriction. |
| ANTARES/ZTF | `allwise`, `bailer_jones`, `gaia`, `gaia_variability`, `gsc`, `twomass` | Preserve catalogue scope, including Gaia probabilities/variability classes. |
| ANTARES/LSST | `allwise`, `gaia`, `gaia_variability`, `gsc`, `milliquas`, `ned` | Audit this survey's fields/identities separately. |

Generic crossmatch plans for Fink and ANTARES, not ALeRCE or Lasair in these sources.
Lasair `with enrichment` consequently fails public planning too. Resolve actual
target/producer intent, rather than choosing the first route or dropping the
family member to hide failure. Lower-level recipe tests are not a complete public
request. A mapping available on another endpoint is not targeted material.

An existing catalogue-scoped example:

```text
object ZTF20aafqubg from ztf via antares
with crossmatch from gaia via antares
filter crossmatch@gaia:antares.classification.assessment.gaia_dsc_star.probability >= 0.99
```

This is a matched-source condition, not the candidate's class. No new live result
for this object is claimed here.

## Completion and maintenance

Require reviewed dispositions, faithful normalized examples, unit/ownership/
multiplicity regressions and executable admitted requests. Update this snapshot
when code/evidence changes; keep unsupported versus dynamically unproven versus
planning ambiguity distinct. Do not assume native population or time/latest proof
from catalogue support; see [discovery integration](discovery_integration.md).

Useful current regressions:
[`test_dsl_crossmatch_recipes.py`](../tests/test_dsl_crossmatch_recipes.py),
[`test_orchestration_crossmatch_recipes.py`](../tests/test_orchestration_crossmatch_recipes.py),
and the provider authoritative-payload tests. Historical fixture reports may retain
old counts alongside follow-ups; calculate current counts with the audit tool.
