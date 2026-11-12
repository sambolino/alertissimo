# Native classification headline policy and integration

Decision date: 11 November 2026. Base: `f44ec81158436784d4c0108f0524b11aeb8acd55`.
Stable work items: **1 and 2**. The former cross-method/universal-winner proposal
is superseded by the user's decision to use broker headlines and explicit defaults.
Historical review documents retain their original context.

## Delivered boundary

The merged policy PR adds eight provider-local `classification_headline.yaml` files, the pure
`data_layer.runtime.classification_headline.derive_headline_fields` function,
counterexample tests and installed-wheel resource checks. That PR introduced no
network calls, dependencies, engines, workflow steps, remote registries or services.
Policy data use the existing packaged provider resource directory.

The pure selector still returns fields without mutating inputs. The completion
change attaches them to a separate `classification@headline:<broker>` record in
each new material view. Native `best.class` and `best.probability` retain their
meaning. `classification.best.coarse_class` and the other explicit headline paths
are now admitted local predicates. The UI reads these stored records through the
shared presentation adapter, without loading or rerunning policy data.

The merged acquisition slice (**PR 2a**) extends fresh ALeRCE/ZTF classification
retrieval: obtain all probability rows, then selected LC and stamp summaries from
`query_objects(oid=..., classifier=...)`. Each call binds the same candidate's
exact ID. Both summary calls are required; a transport failure must not masquerade
as missing LC evidence and trigger fallback. Empty results remain missing evidence.
All native rows, execution provenance and absent version metadata are retained.
No class, probability threshold, ranking or version filter is sent.

This adds two calls per object to a fresh ALeRCE/ZTF classification retrieval,
including explicitly named classifiers. Named selection still runs locally and
preserves the full physical audit. Existing proven discovery-material reuse is
unchanged; that route does not promise to acquire all probability alternatives.
Its reuse proof accepts composed targeted retrievals with declared producer
selectors, while retaining the guards on class filters, limits and other inputs.
ALeRCE/LSST and other brokers keep their existing retrieval recipes.

## Selection rules

| Pair | Headline source | Version compatibility / fallback |
|---|---|---|
| Fink/ZTF | Native `v:classification`, mapped as Fink `best.class` | Published label contract; latest exactly row-linked observation among supplied records; missing ordering or contradictory latest ties abstain |
| Fink/LSST | `f:main_label_classifier`, mapped as Fink `best.class` | Published numeric code contract; source CATS assessments and main crossmatch label are alternatives |
| Lasair/ZTF and LSST | Sherlock `best.class` | Published contextual label contract; no threshold on reliability |
| ALeRCE/ZTF | `lc_classifier`, then `stamp_classifier` only when no LC selected/rank-1 label exists | Native selected summary first; otherwise one unambiguous rank-1 version. Multiple versions abstain. Never choose the greatest version string or score |
| ALeRCE/LSST | `stamp_classifier_rubin_beta_20260421` | Exact observed version string `2.0.2` or endpoint-local integer `202`; no general conversion between version spellings |
| ANTARES/ZTF | Superphot+ | Requires explicit assessment input survey `ztf`; locus membership does not establish it |
| ANTARES/LSST | Unset | `headline_unresolved` |

ALeRCE and ANTARES ordering is an **Alertissimo default**, not an upstream claim.
The ALeRCE/ZTF retrieval integration obtains the broker-selected summary
to resolve multiple LC versions faithfully. Without that summary, the selector
can use one unambiguous rank-1 version; conflicting versions still abstain. The current live
ANTARES capture does not establish the required assessment input-survey provenance.
No adapter may manufacture it from a ZTF or LSST identifier on a locus.

An explicitly reviewed `label_contract` rule covers versions, including absent
version metadata, **only for the named producer's finite published label meanings**.
It does not certify model accuracy or calibrate scores. Exact-version policies
abstain outside their explicit list. Missing version metadata stays null. A
new method name never replaces the chosen method automatically.

Within a selected method, native selected summaries take precedence over a
probability table. Otherwise the broker's rank 1 selects the class; a bool is not
a numeric rank. Multiple versions or conflicting labels at the selected position
produce `conflict`, even if one probability is larger. Identical duplicate
witnesses retain all input IDs; differing metrics are not collapsed to one value.
Observation time can order Fink/ZTF alert labels but is not classifier issue time,
retrieval time or proof that the supplied history is the current complete archive.

## Finite coarse propositions and scientific scope

The table entries explicitly map into this finite set:

`supernova`, `agn`, `variable_star`, `solar_system`, `microlensing`, `kilonova`,
`tidal_disruption`, `cataclysmic_variable`, `artifact`, `satellite`, `transient`,
`periodic`, `stochastic`, `nonperiodic`, `fast_transient`, `long_transient`, `star`,
`galaxy`, `nuclear_transient`.

Membership is categorical support for a broker's selected assessment. It is not
physical confirmation. Explicit SN subtypes imply `supernova`; generic SN does
not imply a subtype. Broad periodic/stochastic/fast/long predictions do not imply
AGN, variable star or a specific transient mechanism. No probability threshold
or comparison across methods is introduced.

All candidate predictions retain `candidate_status=candidate`. Sherlock supplies
a candidate assessment with `basis=contextual`; it is eligible without pretending
to be a light-curve classifier. Sherlock's native reliability is a score with
categories **1 synonym, 2 association, 3 annotation**, not calibrated probability.

Catalogue records are ineligible input records. Fink's catalogue-prefixed native
headlines retain the complete published namespace and `scope=catalogue_association`.
They do not generate a candidate `coarse_class`. All 369 supplied Fink vocabulary
entries are accounted for: 368 ordinary entries plus `Ambiguous` as a sentinel.
The separately observed `Unknown` is also a sentinel. The 358 catalogue labels
are recognized context without guessing a complete SIMBAD/TNS hierarchy; their
state is `recognized_no_proposition`. This is explicit limited coarse coverage,
not an unknown label and not a positive candidate vote.

LVRA is not selected over Sherlock. Its `classification` is the champion model's
extragalactic score, not a categorical winning label. DeSoto, LAISS and other
ANTARES outputs similarly remain alternatives; their scores do not compete here.

## Result and failure contract

| Field / outcome | Meaning |
|---|---|
| `best.native_class` | Selected native label, unchanged |
| `best.coarse_class` | Reviewed candidate-scoped coarse proposition, only when available |
| `best.context_class` | Reserved for an explicitly reviewed catalogue-context coarse mapping; never candidate support |
| `best.scope`, `best.basis`, `best.candidate_status`, `best.subtype` | Independent qualifiers; candidate status is never promoted to confirmed type |
| `best.source_method`, `best.source_version`, `best.source_output` | Selected native method/output metadata; missing version stays missing |
| `best.native_probability`, `best.native_score` | Separate quantities copied only when all selected witnesses agree |
| `best.policy`, `best.mapping_version`, `best.policy_digest` | Named rule, mapping revision and exact content hash |
| `best.input_record_ids` | All attributable native classification inputs, retaining alternatives |
| `best.considered_record_ids`, `best.eligible_record_ids`, `best.selected_record_ids` | Progressively scoped evidence IDs where those stages were reached |
| `missing` | No selected output from a configured method; not a negative classification |
| `sentinel` | Explicit upstream unknown/ambiguous/not-processed value |
| `conflict` | No unambiguous label/version within the eligible output |
| `unsupported_version` | Exact version rule does not cover the supplied output |
| `input_scope_unresolved`, `identity_unresolved`, `observation_order_unresolved` | Missing scope/identity/ordering evidence |
| `headline_unresolved` | No default designated for the pair |
| `recognized_no_proposition` | Known vocabulary entry without an approved coarse proposition |
| `error` + `error_code=unmapped_label` | Vocabulary drift or invalid label type; native value retained, no normalized support |

Malformed policy files raise `HeadlinePolicyError`; they are never treated as
absent evidence. Unknown labels return an explicit error result, not silent
`Unknown`. Integration must surface that result in the public output/UI and must
not turn a missing coarse value into a negative/NOT vote. It may deduplicate
notifications by policy/error/native label; no recurring classifier audit is needed.

Raw native `best` fields and source records remain untouched. The proposed fields
are separate derived content; integration must not merge them over upstream values.

## Completion integration (12 November 2026)

The completion branch includes the discovery reuse fix plus materialization,
normalized predicates/confirmation, bounded initial selection and comparison UI.
Local validation is pending: the assistant has not executed tests or builds for
this change. The user runs the commands below; CI remains deferred to the final
integration-to-main PR unless a specific failure requires it.

Each broker/survey gets a separate derived record. Its input fingerprint covers
native classification records, exactly linked observations and candidate identity.
An unchanged fingerprint reuses the stored policy/result even if policy files
change. A changed input yields a new interpretation in a new view. Physical audit
records and earlier Step views remain intact. A method-specific Get keeps its
existing native selection semantics and suppresses the default headline for that
selected source; a generic Get is required for a default across methods.

Continuation preserves the finalized semantic prefix and its record IDs while
retaining the existing checked physical-call replay. Loading or displaying an old
serialized Portfolio never backfills headlines or loads today's policies.

Normalized Confirm uses the existing complete targeted classification recipe for
each requested broker. It consolidates only that occurrence's own evidence within
one broker before headline selection, then counts at most one vote per broker.
Incoming material cannot fill another broker's missing assessment. Native Confirm
retains its existing assertion-local semantics. Missing/sentinel/conflict/unsupported
outputs abstain under comparisons and NOT. An unknown label is stored as an error;
a coarse predicate encountering it raises an explicit normalization error rather
than silently discarding the candidate. The comparison table surfaces the error
and preserves the native evidence and policy digest.

ANTARES now retrieves and maps Superphot+ class/probability/classifier identifier
and DeSoto class/probability as native locus assessments on both survey routes.
No version or input survey is manufactured. Superphot+ on ZTF-associated loci
therefore remains `input_scope_unresolved`; ANTARES/LSST remains
`headline_unresolved`. Both are useful visible evidence, not normalized votes.
Other anomaly/filter outputs remain in the existing debt ledger and captured data.

For cone or admitted temporal discovery, normalized initial conditions run after
targeted classification acquisition and before global `latest`. The whole original
predicate is retained. A normalized condition alone never opens an unbounded
archive scan. Provider completeness/time guards remain in force.

Examples:

```text
objects ZTF20aaaaaaa from ztf via alerce
with classification via alerce, fink, lasair
filter classification.best.coarse_class = "supernova"
```

```text
objects ZTF20aaaaaaa from ztf via alerce
where classification.best.coarse_class = "supernova"
confirm by 2 via alerce, fink, lasair
```

```text
objects from ztf via alerce
inside (10, 20, 5arcsec)
where classification.best.coarse_class = "supernova"
latest 1
```

A native label/metric predicate still uses `best.class` / `best.probability`.
A headline label/metric predicate uses `best.coarse_class` /
`best.native_probability` on the same derived record; heterogeneous probabilities
are never averaged or compared to select the headline. These examples describe
candidate assessment support, not physically confirmed classifications.

The integration branch exception remains limited to
`integration/classification-headlines`. The final PR to `main` runs the ordinary
validation jobs. No manual workflow dispatch is required for intermediate PRs.
The remaining MD work is outside this topic.

## Completion validation (user-run only)

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_classification_headline_policy.py \
  tests/test_classification_headline_integration.py \
  tests/test_dsl_alerce_classification.py \
  tests/test_dsl_multi_broker_classification.py \
  tests/test_alerce_semantic_search.py \
  tests/test_orchestration_classification_material.py \
  tests/test_dsl_confirm_scope.py \
  tests/test_orchestration_confirmation.py \
  tests/test_api_continuation.py \
  tests/test_app_classification_comparison.py \
  tests/test_app_search_portfolios.py \
  tests/test_app_plot_semantic_records.py \
  tests/test_antares_registry_architecture.py \
  tests/test_portfolio_serialization.py
PYTHONPATH=. python -m alertissimo.data_layer.runtime.mapping_schema --all
PYTHONPATH=. python scripts/check_release_package.py
```

The package check covers the new shared presentation module and runtime resources.
None of these commands was run during preparation. Historical evidence below
belongs to its stated earlier slice, not this completion change.

## Evidence and local validation

Policies cite the published vocabulary/docs and existing frozen captures. The
11 November changes add no new live-provider claim. Preparation ran only static
Python syntax parsing, JSON/YAML-subset parsing and Git whitespace/patch checks.
Project imports, pytest, builds, applications and live provider calls were **not
run here**; the user runs tests locally.

From an existing development environment:

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_classification_headline_policy.py \
  tests/test_antares_registry_architecture.py \
  tests/test_alerce_classification_mappings.py \
  tests/test_portfolio_serialization.py
PYTHONPATH=. python scripts/check_release_package.py
```

The focused suite checks selection, ambiguity, sentinel/error separation,
unknown versions, exact attribution, subtype implications, unchanged native
records and the real frozen ALeRCE/LSST probability shape. The package check is
needed because eight runtime policy resources are added; it now loads each from
the installed wheel. Existing packaging globs already include these files.

The semantic-registry workflow includes the new tests. No additional manually
dispatched workflow or live broker smoke test is needed for this opt-in PR.

For the PR 2a acquisition change, preparation performs static Python syntax and
YAML/JSON parsing plus Git whitespace/bundle verification only. Runtime tests are
prepared, not reported as passed. Focused local validation for acquisition changes
includes:

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_dsl_alerce_classification.py \
  tests/test_dsl_multi_broker_classification.py \
  tests/test_discovery_integration_acceptance.py \
  tests/test_orchestration_classification_recipes.py \
  tests/test_orchestration_classification_material.py \
  tests/test_classification_headline_policy.py \
  tests/test_alerce_ztf_endpoint_contracts.py \
  tests/test_alerce_registry_architecture.py \
  tests/test_alerce_classification_mappings.py \
  tests/test_alerce_semantic_search.py \
  tests/test_api_continuation.py
PYTHONPATH=. python -m alertissimo.data_layer.runtime.mapping_schema --all
PYTHONPATH=. python scripts/check_release_package.py
```
