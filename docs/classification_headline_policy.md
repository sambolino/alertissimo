# Classification headline policy: ELAsTiCC code sets

Decision: 13 November 2026, replacing the flat coarse vocabulary. Base:
`15613e7` on `integration/classification-headlines`. Stable work items **1 and 2**.
The dictionary is `alertissimo/data_layer/semantic_model/classification_taxonomy.yaml`;
all eight provider policies use `mapping_version: elasticc-v1` and policy IDs ending
in `-v2`. No recipes, endpoints, capabilities, grammar or acquisition rules change.

## Dictionary and scope

Codes 0–2332 reproduce the ELAsTiCC hierarchy from Alex Malz and Rob Knop,
[LSSTDESC/elasticc commit 818ae71](https://github.com/LSSTDESC/elasticc/blob/818ae71e78d20b6f41810d7d6d9108ba4c17bcb1/taxonomy/taxonomy.ipynb).
Ancestry follows explicit `parent` links, including Meta codes 0, 100, 200 and 300.
It never follows digit arithmetic. The six nodes 9000, 9100, 9200, 9210, 9220 and
9300 are reviewed Alertissimo-local extensions for moving, Solar System and
artificial sources; they are not ELAsTiCC classes. No comet node is introduced.

The cached dictionary validates unique integer codes, existing parents, acyclicity,
unique trimmed/case-folded aliases and valid referenced codes. Every `/Other`
node has a meaning or `used_for: unused`. Only these meanings may be used by
provider mappings: 2321 other periodic variable stars, 2331 young stellar objects,
2231 classical novae. `/Other` codes behave as ordinary leaves in comparison.
A policy referencing an unused `/Other` node is a maintainer error.

Every node has decimal-code and lower-snake-case name aliases. Matching uses exact
case-folded, trimmed text; no fuzzy or regex resolution. Unknown aliases report
up to five `difflib` suggestions without accepting a guessed meaning. The dictionary
also contains readable aliases such as `snia`, `kilonova`, `microlensing`, `lpv`,
`yso`, `classical_nova`, `solar_system`, `satellite` and `moving`.

| Union alias | Codes | Reason |
|---|---|---|
| `supernova` | 2220, 2242, 2246 | ELAsTiCC places SLSN and PISN under Long |
| `cataclysmic_variable` | 2231, 2234 | Classical novae plus dwarf novae |
| `variable_star` | 2233, 2234, 2320, 2331 | Reviewed provisional grouping; membership remains an open decision |

There is no `nova` alias. Aliases are unique; a union is one unambiguous alias
whose meaning is a code set, not several competing alias definitions.

## Selection and attribution

| Pair | Selected source | Compatibility / fallback |
|---|---|---|
| ALeRCE/ZTF | `lc_classifier`, then `stamp_classifier` | `label_contract`; fallback only when LC has no selected/rank-1 output |
| ALeRCE/LSST | `stamp_classifier_rubin_beta_20260421` | Exact version `2.0.2` or integer `202`; no conversion between spellings |
| Fink/ZTF | Native `v:classification` | Label contract; latest exactly row-linked observation; missing order or contradictory latest ties abstain |
| Fink/LSST | Native `f:main_label_classifier` | Numeric label contract; source CATS and crossmatch assessments remain alternatives |
| Lasair/ZTF and LSST | Sherlock | Contextual label contract; no reliability threshold |
| ANTARES/ZTF | Superphot+ | Requires explicit classifier input survey; captured locus membership cannot supply it |
| ANTARES/LSST | No default | `headline_unresolved` |

ALeRCE and ANTARES defaults are Alertissimo choices, not upstream endorsements.
Within a selected method, native selected summaries precede rank-1 probability
outputs. A boolean is not a numeric rank. Scores, probability magnitudes, version
ordering and retrieval times never choose a winner. Exact-version signatures
still include label and version; unsupported versions abstain.

For `label_contract`, the conflict signature is now the label alone. Identical
labels from different versions agree; different labels remain `conflict`.
One reported version remains scalar, including null. Several distinct versions
are retained as a sorted tuple of `_key` string forms (a missing version in a
mixed set is represented as `"null"`). Selected record IDs retain every witness;
differing metrics do not collapse into one metric. This fixes agreeing ALeRCE
LC versions without choosing the newest model.

Fresh ALeRCE/ZTF retrieval still obtains probability rows plus selected LC and
stamp summaries for the exact candidate ID. Both summary calls are required;
transport failure is not missing evidence. Explicit classifier selection, proven
discovery reuse, all other retrieval recipes and provider completeness guards
are unchanged. No extra calls are introduced by taxonomy comparison.

## Provider mappings and reviewed notes

The eight policy files are the authoritative full native-label tables. Candidate
rows require nonempty dictionary code lists; catalogue-association rows require
null codes. Existing scope, status and subtype metadata remain intact.

- **ALeRCE/ZTF:** SNIa 2222; SNIbc 2223; SNII 2224; SLSN 2242; SN uses the
  supernova union. QSO/AGN/Blazar map to 2332; CV/Nova to 2234+2231; YSO 2331;
  LPV 2326; E 2325; DSCT 2324; RRL 2323; CEP 2322; Periodic-Other 2321;
  VS uses variable_star; asteroid 9220; bogus 1000. Removed unreachable labels:
  EA, EB/EW, Microlensing, Periodic, RRLab, RRLc, RSCVn, SESN, SNIIb, SNIIn,
  Stochastic, TDE, Transient, satellite. Static inspection of the probability and
  headline fixtures found no discrepancy: all 19 retained labels are reachable.
- **ALeRCE/LSST:** AGN 2332, SN supernova union, VS variable_star union,
  asteroid 9220, bogus 1000. All five labels occur in declared-method fixtures.
- **Fink/LSST:** 11→2220, 12→2230, 13→2240, 21→2320, 22→2332; −1 stays a
  sentinel. The last mapping follows Fink's `CATS_CLASS_DICT` label
  `non-Periodic (AGN)` at [fink-science cfb7ced](https://github.com/astrolabsoftware/fink-science/blob/cfb7ced/fink_science/rubin/cats/utilities.py).
- **Fink/ZTF:** SN candidate uses the supernova union; Early SN Ia candidate
  2222, SLSN candidate 2242, Kilonova candidate 2232, Microlensing candidate
  2235, Solar System candidate/MPC 9200, CTA Blazar high/low state 2332.
  Tracklet maps only to Moving 9000: satellite-glint versus fast-moving-object
  semantics are unverified, so narrower queries remain unresolved. Every SIMBAD
  and TNS prefixed row is retained and gains a bare catalogue row. The five shared
  labels **AGN, Galaxy, Nova, QSO, SN** each have one merged bare row. There are
  no collisions with Fink-own labels or sentinels. The 368 original rows plus
  353 unique bare rows give 721 vocabulary rows; Unknown/Ambiguous remain sentinels.
  Catalogue labels carry `recognized_no_proposition` and never vote.
- **Lasair/ZTF and LSST:** SN uses the supernova union; AGN 2332; VS the
  variable_star union; CV 2234+2231; BS 1000+2320+2233; NT 2332+2243+2220.
  BS (near a bright star: likely artefact or stellar) and NT (nuclear position)
  are contextual unions, not classes. Sherlock reliability remains a native
  score (1 synonym, 2 association, 3 annotation), not a probability. LVRA is not
  selected as a categorical label.
- **ANTARES/ZTF:** SN Ia 2222; SN II/SN IIn 2224; SN Ibc 2223; SLSN-I 2242.
  Existing subtypes remain. Superphot+ assumes the object is a supernova and
  must not be enabled as a voter until a conditional-classifier rule is agreed
  with the maintainer. No input survey is fabricated: actual material continues
  to abstain with `input_scope_unresolved`. DeSoto and other methods remain alternatives.
- **ANTARES/LSST:** disabled default unchanged apart from policy schema/version.

## Stored fields and comparison

Each broker retains its separate `classification@headline:<broker>` record.
Native `best.class` and other native fields are unchanged. `best.native_class`
retains the selected native label. `best.taxon` replaces the old coarse/context
fields: it is a sorted tuple of integer codes, set only for candidate scope with
status `available`. Catalogue context never gets a candidate code set.

Scope, basis, candidate status, subtype, method/version/output, metrics, policy
ID/version/digest and input/considered/eligible/selected record IDs are retained.
Unavailable outcomes remain explicit: missing, sentinel, conflict,
unsupported_version, input_scope_unresolved, identity_unresolved,
observation_order_unresolved, headline_unresolved, recognized_no_proposition and
error/unmapped_label. Candidate assessments never become physical confirmation.

For record set R and query set Q, `classification.best.taxon = <literal>` gives:

1. **True:** every r is a descendant-or-self of some q.
2. **False:** no r/q pair overlaps by ancestry in either direction.
3. **Unknown:** all remaining cases, including a broader record against a narrower query.

`!=` inverts True/False and preserves unknown. NOT preserves unknown. Only True
selects or votes; Confirm retains broker-local evidence and counts each broker
at most once. Any other taxon comparison operator is a validation error.
SNIa supports snia and supernova but opposes snii. CATS 11 supports supernova but
is unknown against snia. Sherlock SN supports supernova; NT is unknown against
tde and opposes solar_system.

Unmapped native labels remain visible errors in the stored record/UI, contribute
unknown in predicates and no vote in Confirm, and no longer raise at evaluation.
Malformed policy/dictionary data still raise `HeadlinePolicyError` as maintainer
errors. Fixture drift regressions check declared-method labels instead of making
data drift crash a runtime filter.

## Approved amendment to Part E, step 3

The maintainer approved extending the existing `PredicateLiteral.value` with
`tuple[StrictInt, ...]`. The tuple must be nonempty, sorted and duplicate-free;
booleans and numeric strings are rejected as tuple elements. Equal code sets
therefore have equal immutable representations and hashes. The existing
`ComparisonPredicate` validator permits tuples only opposite a `classification`
reference at `best.taxon`, under `=` or `!=`; all other placements are rejected.

The existing DSL predicate-lowering function resolves aliases and integer/string
codes before constructing the comparison. The surface script retains the alias
exactly as typed, including case and spaces within the quoted literal. Existing
surface-based UI and diagnostics keep the user's words; no reverse alias is
invented from the code tuple. Unknown-alias errors quote the original literal.
The lowered IR holds only codes. Serialized JSON lists validate back into equal,
frozen tuples, so continuation does not reinterpret saved aliases if alias
membership later changes. ELAsTiCC ancestry remains immutable by contract.

Provider predicate realization explicitly refuses tuple literals in either
operand position, regardless of future provider bindings. No tuple reaches a
physical provider parameter. Regression cases cover this guard, strictness,
placement, JSON round trips, saved workflows and unchanged surface text.
No further schema, grammar, endpoint, capability or recipe extension is needed.

## Materialization, presentation and examples

The native-evidence fingerprint and immutable materialization rules are unchanged.
Unchanged evidence reuses stored interpretations; new evidence creates a new view.
Earlier results and native alternatives remain intact. Loading or displaying a
serialized Portfolio never derives new scientific fields or reruns provider policy.
The presentation reads stored codes and looks up dictionary names solely for
formatting, e.g. `2222 Ia` and `9220 Asteroid (Alertissimo ext.)`.

```text
objects ZTF20aaaaaaa from ztf via alerce
where classification.best.taxon = "supernova"
confirm by 2 via alerce, fink, lasair
```

```text
objects from ztf via alerce
inside (10, 20, 5arcsec)
where classification.best.taxon = "snia"
latest 1
```

```text
filter classification.best.taxon != 2222
```

A broader SN result remains unknown in the final example. Normalized discovery
still acquires the required material before filtering and before global latest;
a normalized condition alone never authorizes an unbounded archive scan.
Headline metrics use `best.native_probability`/`best.native_score` on the same
assertion. Heterogeneous metrics are never compared to select a headline.

## Open decisions (not implemented)

1. Whether ALeRCE/ZTF should prefer `lc_classifier_BHRF_forced_phot`, which has TDE.
2. Verification of Fink Tracklet semantics.
3. An eligibility rule for conditional classifiers such as Superphot+.
4. Review of `variable_star` union membership.
5. Whether Confirm should later restrict support by `best.basis`.

## Validation and handoff

Exactly one new repository file is introduced: the taxonomy dictionary. Code,
policy, ontology, documentation and regressions otherwise use existing files.
Static inspection found no unmapped captured labels for Fink/ZTF (9 distinct),
Fink/LSST (2), Lasair/ZTF (1) or Lasair/LSST (1). Existing ANTARES/ZTF fixture
files contain no Superphot+ labels: its mapping is covered by synthetic cases,
not a claimed captured classifier example.

The ALeRCE reachability and Fink collision findings above are static fixture/data
inspection, not executed regression results. Tests, builds, CI and live provider
calls were not run during preparation. The existing integration-to-main CI
failures require separate review; this change does not claim to clear them.
The user performs local validation and creates the PR into
`integration/classification-headlines`; no push, PR mutation or merge is performed
by the assistant.

## Files in this change

New: `alertissimo/data_layer/semantic_model/classification_taxonomy.yaml`.

Modified existing files:

- `.agents/skills/semantic-orchestration-change/SKILL.md`
- `ARCHITECTURE.md`
- `README.md`
- `alertissimo/app_plot.py`
- `alertissimo/data_layer/presentation/portfolio_classification.py`
- `alertissimo/data_layer/providers/alerce/lsst/classification_headline.yaml`
- `alertissimo/data_layer/providers/alerce/ztf/classification_headline.yaml`
- `alertissimo/data_layer/providers/antares/lsst/classification_headline.yaml`
- `alertissimo/data_layer/providers/antares/ztf/classification_headline.yaml`
- `alertissimo/data_layer/providers/fink/lsst/classification_headline.yaml`
- `alertissimo/data_layer/providers/fink/ztf/classification_headline.yaml`
- `alertissimo/data_layer/providers/lasair/lsst/classification_headline.yaml`
- `alertissimo/data_layer/providers/lasair/ztf/classification_headline.yaml`
- `alertissimo/data_layer/runtime/classification_headline.py`
- `alertissimo/data_layer/semantic_model/ontology.yaml`
- `alertissimo/dsl/predicate_lowering.py`
- `alertissimo/orchestration/ir/predicates.py`
- `alertissimo/orchestration/normalization/predicate.py`
- `alertissimo/orchestration/planner/predicate_realization.py`
- `docs/classification_comparison_view.md`
- `docs/classification_evidence_design_plan.md`
- `docs/classification_fink_ztf_native_labels.md`
- `docs/classification_headline_policy.md`
- `docs/next_functional_work.md`
- `tests/test_app_classification_comparison.py`
- `tests/test_classification_headline_integration.py`
- `tests/test_classification_headline_policy.py`
- `tests/test_dsl_alerce_classification.py`
- `tests/test_dsl_predicate_realization.py`
