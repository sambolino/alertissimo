# Discovery and application integration

Prepared: 28 October 2026.

Baseline: `sambolino/alertissimo` `main` at
`7dcff34ecc7320afd1fcd97247d60abe1fde6c61`.

External reference: `bibinthomas123/nucleuswatch` at
`f0b4ee7fff4db6faf508d01e5b8b0311f0e3d52d`. Record a new reference SHA if
the integration comparison uses a later version.

## Objective

Fix the three problems reported by Bibin Thomas, complete useful semantic
discovery through the existing recipe system, and make a representative
nucleuswatch workflow obtain its candidates and broker evidence through
Alertissimo. Nucleuswatch remains responsible for its scientific analysis,
ranking, presentation, and volunteer workflow.

Veljko implements and merges this series. Bibin is invited to test the resulting
integration and report differences from his direct broker pipeline. His
participation is useful but is not a prerequisite for implementing any branch.

This is an extension of the current architecture. Keep WorkflowIR, the public
DSL, provider recipes, physical endpoint contracts, mappings, staged execution,
and Portfolio as the existing boundaries. No new orchestration layer, replacement
domain model, central parameter registry, or application-specific planner is
needed.

The first complete acceptance target is ZTF. Audit all eight existing
broker/survey contracts during their provider branch; activate equivalent Rubin
support where the actual contract permits it. Different Rubin APIs do not inherit
ZTF support automatically. Publish the exact support matrix, including explicit
deferrals, rather than making an empty recipe stand for support.

## Sources of truth

| Source | Owns |
| --- | --- |
| Existing DSL and IR | Scientific intent, predicates, time context, target identity, and workflow order |
| Existing ontology | Scientific records, fields, units, and qualifiers |
| Provider `endpoints.yaml` | API signature, transport, required parameters, defaults, encoding, and physical limits |
| Provider `mappings.yaml` | Response fields, meaning, normalization, and partition identity |
| Provider `capabilities.yaml` | Provider-local recipes and request-side semantic translations |
| CapabilityGraph and existing resolvers | Compiled evidence, feasibility, recipe selection, and diagnostics |
| Portfolio and execution provenance | Returned scientific evidence, candidate ownership, and the calls that produced it |
| Nucleuswatch | Application policies, taxonomy choices, science calculations, ranking, and presentation |

Use the existing operation names, including `semantic_search`, `lookup`,
`get_classification`, `get_lightcurve`, and `get_crossmatch`. Provider endpoint
names remain local. A declaration of possible mapped material is not proof that
every response, response mode, or requested projection contains it.

## Baseline findings

1. ALeRCE ZTF classification retrieval has two feasible recipe alternatives,
   `query_probabilities` and `query_object`. The unconstrained classification
   example passes public validation but fails planning with ambiguity.
2. The ZTF `query_probabilities` recipe passes `classifier` to a Python client
   method that does not accept it in the inspected ALeRCE 2.3.1 installation.
   Resolve the actual supported contract; do not depend on an accidental version.
3. `within` is already parsed and represented by IR `TimeContext`. Missing support
   is the verified translation into discovery request parameters and its execution.
4. Only ALeRCE currently declares `semantic_search` recipes. Fink ZTF already has
   a physical `latests` endpoint and many relevant response mappings, but lacks
   the semantic discovery recipe and class/time bindings.
5. The recipe loader's required-parameter check does not currently regard a
   predicate binding alone as an assignment. Required-at-load and
   required-for-this-request checks need to work together.
6. Lasair's split query contract and ANTARES's Elasticsearch query contract need
   concrete translations before they can implement semantic discovery. Their
   existing lookup/cone recipes do not establish generic search support.
7. `distnr` is intentionally unmapped because it is a detector-pixel distance,
   while the existing angular separation leaf uses arcseconds. The email's claim
   that all three nuclear-selection fields are already mapped is incorrect.
8. Alertissimo already exposes `DSLExecutionResult`, Portfolio serialization,
   candidate identity helpers, and photometry DataFrame views. Extend and document
   those facilities; do not introduce another normalized result model.

## Correctness boundaries

- Resolve relative time once for a discovery occurrence against one UTC reference
  instant. Preserve the resolved bounds in execution evidence. Static validation
  must not contact providers or permanently substitute the validation-time clock.
- Keep relative intent in IR. Absolute request values belong to binding/execution.
  Reuse is valid only when the requested population and resolved bounds match;
  an old search is not equivalent merely because both programs contain `within 7d`.
- Declare what `within` constrains for each admitted search. An alert's observing
  time, an object's first/last detection, and a processing timestamp are different
  quantities. An object-summary last-time filter does not prove that an arbitrary
  historical alert-window search is complete.
- A classification stream and an object's current classification may describe
  different populations. Admit pushdown only for the semantics that the actual
  endpoint and normalized evidence establish. Do not silently change predicate
  meaning in order to make a recipe runnable.
- A required parameter supplied by a predicate remains required. Missing,
  conflicting, ineligible, or wrongly qualified predicates must fail before the
  first network call. Declaring a binding is not proof that a particular request
  supplies a value.
- Pushdown must preserve a candidate superset. Residual predicates require the
  relevant normalized evidence; unavailable material cannot be manufactured by
  local filtering. Preserve current AND/OR/NOT and qualifier semantics.
- Retrieval limits are physical limits, not scientific sample definitions.
  Complete discovery, bounded previews, and incomplete results must be explicit.
  Never silently call a capped response the complete population.
- Group discovered rows by the existing `(origin, object_id)` ownership rules.
  Keep distinct provider evidence and detection identity. Do not flatten several
  objects into a single light curve.
- Preserve loaded detections, broker-reported detection counts, forced photometry,
  and non-detections as their existing distinct material. Selecting candidates
  must not silently discard their measurements.
- Keep equal feasible alternatives ambiguous unless semantic evidence establishes
  a unique choice. YAML order and arbitrary preference scores are not selection
  policies.
- Provider failures and missing credentials are separate from contract defects.
  A live timeout may be unavailable; a Python keyword mismatch is a failure.

## Sequential PRs

Each branch starts from updated `main` after its predecessor is merged. Do not
pre-create future branches. The branch names below are proposed names, not
existing refs. Split a branch further if its implementation becomes difficult to
review, keeping the same order and acceptance boundary.

| Branch | Deliverable |
| --- | --- |
| `fix/integration-01-alerce-classification` | Correct ALeRCE classification contracts, remove the demonstrated ambiguity, and align public validation with planning |
| `feat/discovery-02a-predicate-bindings` | Admit required predicate parameters through existing recipes and reject unbound requests before execution |
| `feat/discovery-02b-time-bindings` | Complete time-context encoding and fixed-clock/replay handling through existing binding/execution interfaces |
| `feat/discovery-03a-fink-result-limit` | Reject visibly saturated Fink JSON responses through the existing executor and record the provider contract audit |
| `feat/discovery-03b-fink` | Activate verified Fink ZTF class/time discovery using the cap guard; keep Rubin tag search separate |
| `feat/discovery-04-alerce` | Complete admitted class/time search combinations in existing ALeRCE recipes |
| `feat/discovery-05-lasair` | Implement a bounded, declared semantic-search translation for verified Lasair query fields |
| `feat/discovery-06-antares` | Implement a bounded, declared semantic-search translation for verified ANTARES query fields |
| `feat/integration-07-required-material` | Complete the small set of normalized inputs required by the reference ZTF workflow |
| `feat/integration-08-result-access` | Document and complete application access to per-candidate Portfolio evidence |
| `test/integration-09-acceptance` | Add the reference workflow, direct-versus-Alertissimo comparison, support matrix, and handoff runbook |

### PR 01 — ALeRCE classification retrieval

Reproduce these exact reports through the public API:

```text
objects ZTF21abfmbix from ztf via alerce
with classification via alerce
```

```text
objects ZTF21abfmbix from ztf via alerce
with classification from lc_classifier via alerce
```

Inspect the installed official client's method signature and authoritative REST
payload. Make the physical declaration accurate. Prefer retrieval of actual
classification material through the verified probabilities interface. Treat
classification already embedded in required discovery material through the
existing material/reuse proof, rather than keeping an unnecessary competing
fresh-retrieval alternative.

If the upstream method returns all classifiers and cannot restrict the request,
retrieve them and apply the requested classifier selection to normalized
classification records. Preserve classifier identity, model version, label, rank,
and probability where available. Do not pass unsupported keywords, invent an
upstream filter, silently ignore the selector, or select an unrelated classifier.

Audit Rubin's different probability contract independently. Keep currently valid
reuse behavior. Do not make one provider recipe repair bypass the shared
resolver. Public validation must catch deterministic ambiguity or binding defects
that the same canonical workflow would encounter during planning.

Primary locations: ALeRCE provider declarations; shared classification resolver;
DSL classification checks; planner; existing normalization/finalization paths if
local classifier selection needs completing.

Acceptance:

- Both ZTF examples validate and execute on suitable recorded responses.
- Unconstrained retrieval retains valid classifiers without endpoint ambiguity.
- A constrained result selects the requested classifier, including an explicit
  empty/absent outcome when that classifier has no result.
- No `classifier` keyword reaches a Python method that does not accept it.
- A synthetic genuinely ambiguous recipe still fails static admission.
- Existing discovery-material classification reuse and continuation remain valid.

Focused commands:

```bash
python -m pytest -q tests/test_alerce_ztf_endpoint_contracts.py tests/test_alerce_classification_mappings.py tests/test_orchestration_classification_recipes.py tests/test_orchestration_classification_material.py tests/test_dsl_classification_recipes.py tests/test_dsl_public_api.py
```

### PR 02 — Discovery input bindings

Split into two sequential reviews: **02a** implements required predicate inputs;
**02b** implements time bindings and clock/replay guarantees. Provider activation
remains in PRs 03 onward. PRs 02a and 02b are merged.

Complete two missing parts of the existing recipe/binder contract:

1. Required physical parameters may be supplied by an eligible predicate binding.
   The compiler validates the declaration; the request resolver checks that the
   actual predicate supplies one compatible value. Keep endpoint defaults and
   fixed values in their existing owners.
2. A recipe can feed `TimeContext` into declared endpoint encodings. Resolve
   relative windows at the existing execution/binding boundary and encode absolute
   UTC bounds or MJD/JD values as required by the endpoint.

Use existing `from`, binding roles, request transforms, and immutable plan models.
Add only the missing transform/operand support. Do not add a temporal planner,
expression language, second parameter registry, or arbitrary callable loading.
Freeze the minimal YAML syntax only after checking the current binder contract.

For reproducibility, make the reference instant injectable at the existing
execution/binding boundary. If a small optional public argument is needed, wire it
through `execute_dsl` without changing ordinary calls. All calls that implement
one discovery occurrence must use the same instant. Preserve timezone handling,
sub-day precision, and provider-specific boundary inclusion rules.

Acceptance:

- Fixed-clock tests turn `within 7d` into exact, reproducible physical bounds.
- Explicit bounds encode without changing their meaning.
- Missing class, conflicting assignments, unsupported operators, and wrong
  qualifiers fail before execution.
- A bound required class is accepted; an unbound required class is rejected.
- Repeated discovery with different resolved bounds cannot reuse stale results.
- Validation, planning, and binding agree on the supported input forms.

Add `tests/test_discovery_time_bindings.py` for the new fixed-clock cases.

```bash
python -m pytest -q tests/test_recipe_registry.py tests/test_request_transforms.py tests/test_discovery_time_bindings.py tests/test_orchestration_binding.py tests/test_orchestration_predicate_recipes.py tests/test_orchestration_discovery_eligibility.py tests/test_dsl_candidate_recipes.py
```

### PR 03 — Fink semantic discovery

Split into **03a**, the physical JSON response-cap guard and source audit, and
**03b**, the semantic recipe and admission of verified class/time populations.
03a does not activate semantic discovery or claim that every unsaturated response
is complete. The audit found provider-side grouping and post-filtering for some
routes; those require separate admission evidence. See
[the 03a runbook](discovery_03a_fink_result_limit.md). Create 03b only after 03a
is merged. Window subdivision, if added, must preserve verified boundary semantics
and operational limits; until then saturation must remain an explicit failure.

Add the ZTF `semantic_search` recipe for the existing `latests` endpoint. Declare
the eligible classification equality binding to `class`, plus the verified time
bindings to `startdate` and `stopdate`. Keep method, defaults, field projection,
and physical limits in the endpoint contract. Existing GET and an application's
use of POST are not inherently a defect; verify supported transport before
changing it.

Required acceptance query:

```text
objects from ztf via fink
within 7d
where classification.best.class = "SN candidate"
```

Then exercise the same search with a residual filter and downstream light-curve
or classification retrieval. Confirm that endpoint-local mappings supply the
requested summary identities and predicate material. A missing class should have
a clear diagnostic instead of triggering an arbitrary default stream.

Handle repeated alerts for one object through current candidate partitioning.
Implement complete retrieval using verified window subdivision/pagination, or
expose an explicit bounded/incomplete result through the existing result and
diagnostic facilities. Continue subdividing while the upstream contract permits;
do not inherit nucleuswatch's silent one-day stopping limit. If completeness
cannot be established for a saturated interval, report it visibly. An `n` limit
does not implement global `latest N` over a filtered object population.

Audit Rubin's actual tags/class-search interface and available classifier fields.
Activate an equivalent recipe only if its input and population semantics are
verified. Otherwise record the exact unsupported combinations and the endpoint
evidence needed for a later small provider PR. Do not invent a Rubin class
endpoint or treat a fixed science tag as an unrestricted class query.

Add `tests/test_fink_semantic_search.py` with recorded response replays.

```bash
python -m pytest -q tests/test_fink_semantic_search.py tests/test_fink_ztf_authoritative_payloads.py tests/test_fink_registry_architecture.py tests/test_orchestration_search_recipes.py tests/test_orchestration_endpoint_pagination.py tests/test_orchestration_residual_pruning.py tests/test_dsl_candidate_recipes.py
```

### PR 04 — Complete ALeRCE discovery combinations

Extend the existing semantic-search recipes with verified classification and time
translations for ZTF and Rubin. Reuse PR 02's binding machinery. Check physical
filter names and range encodings against each actual client/API contract.

Class selection may require both a classifier and a class name. Retain that
distinction. Document whether a time filter constrains first detection, last
detection, or another explicitly mapped time. A current object summary cannot
reconstruct arbitrary historical alert availability; retain explicit deferral for
requests whose semantics it cannot establish.

Preserve existing predicate pushdown, residual evaluation, pagination, and global
selection. Include mixed supported/unsupported predicates and classifier
qualifiers. No broad refactor of ALeRCE adapters is part of this branch.

Add `tests/test_alerce_semantic_search.py`.

```bash
python -m pytest -q tests/test_alerce_semantic_search.py tests/test_alerce_ztf_endpoint_contracts.py tests/test_alerce_lsst_authoritative_payloads.py tests/test_orchestration_search_recipes.py tests/test_orchestration_predicate_recipes.py tests/test_orchestration_selection_recipes.py tests/test_dsl_predicate_realization.py
```

### PR 05 — Lasair semantic discovery

Use the existing query endpoint to implement a deliberately bounded subset of
semantic discovery over verified fields. Start with object identity/summary,
recency, and mapped classification/context fields required by the reference
workflow. Declare the selected columns and tables needed for that result shape.

Translate the existing predicate representation at the current planning/binding
boundary. Physical column names must come from verified declarations. Escape
literal values and preserve comparison operators. Support conjunctions first if
that is the smallest complete implementation; defer unimplemented OR/NOT forms
before network access rather than changing their meaning.

The current `conditions` encoder also serves target-ID membership in composite
retrieval. Add the discovery form without breaking that existing use or relabeling
an arbitrary condition as a target ID. Keep raw `sql_query` and semantic discovery
as distinct intents even though they may use the same physical endpoint.

Verify limit/offset behavior, ordering, and identity projection. A page limit is
not a complete search. Audit ZTF and Rubin separately; split the branch by survey
if contracts differ substantially. Keep unsupported combinations in the matrix.

Add `tests/test_lasair_semantic_search.py`.

```bash
python -m pytest -q tests/test_lasair_semantic_search.py tests/test_orchestration_sql_recipes.py tests/test_orchestration_search_recipes.py tests/test_orchestration_binding.py tests/test_orchestration_composite_cone_recipes.py tests/test_lasair_ztf_compact_cone_summary.py tests/test_orchestration_endpoint_pagination.py
```

### PR 06 — ANTARES semantic discovery

Declare semantic discovery through the existing Elasticsearch `search` endpoint.
Translate a bounded set of verified semantic predicates into its required query
dictionary, preserving the contract's single top-level `query` key.

Start with the mapped object-summary, time, and catalogue/filter information that
the actual index supports. Catalogue membership is not automatically a physical
transient classification. Do not make an AGN catalogue association an equivalent
substitute for an arbitrary `classification.best.class` condition.

Use typed literals, whitelisted field mappings, explicit operators, and verified
date formats. Reuse the existing iterator/executor path. Confirm the output
contains the candidate identity and scientific material needed for residual
conditions. Audit both surveys independently. This branch does not introduce an
Elasticsearch framework or expose raw query syntax in the public scientific DSL.

Add `tests/test_antares_semantic_search.py`.

```bash
python -m pytest -q tests/test_antares_semantic_search.py tests/test_antares_registry_architecture.py tests/test_antares_ztf_authoritative_payloads.py tests/test_antares_lsst_authoritative_payloads.py tests/test_orchestration_search_recipes.py tests/test_orchestration_discovery_eligibility.py tests/test_dsl_candidate_recipes.py
```

### PR 07 — Material required by the reference workflow

Inventory the reference workflow's actual inputs before editing mappings. Keep
the inventory with the final integration guide and classify each item as:
available; implemented in this series; externally supplied by nucleuswatch; or
explicitly deferred with a reason.

The initial inventory includes object IDs, positions, observation times,
photometry/errors/bands, detection IDs, classification identity/version/values,
Pan-STARRS association separation and star/galaxy score, reference-source pixel
distance, detection-history count, positive-subtraction indicator, and first/last
history times. Inspect actual payload availability per endpoint, not just the
union of a provider's mappings.

Add the smallest compatible pixel-distance field under the existing reference
source context for `distnr`, following the metamodel. Keep angular separation in
arcseconds. Move only newly mapped entries out of the unmapped inventory, retaining
other exclusions. No measurement-family remodel or global ontology redesign.

Use already retained summary and classification material for SIMBAD, TNS, and
Sherlock context where supported. Keep reported counts independent of loaded
point counts. Preserve missing values, sentinels, and subtraction signs.

Inspect cutout retrieval separately. If one verified Fink response mode can use
the existing `data_product` representation, complete that path with a small
fixture-backed change, splitting PR 07 if needed. If it needs a larger binary
transport/export change, mark it explicitly deferred. Legacy host-catalogue TAP
lookups, the TDE model, Zooniverse publishing, and scheduling remain external in
this series; they do not block broker integration.

Add `tests/test_reference_workflow_material.py`.

```bash
python -m pytest -q tests/test_reference_workflow_material.py tests/test_semantic_model_validation.py tests/test_semantic_paths.py tests/test_mapping_schema.py tests/test_payload_mapping_coverage.py tests/test_fink_ztf_authoritative_payloads.py tests/test_orchestration_product_recipes.py
```

### PR 08 — Application access to results

Use `execute_dsl`, `DSLExecutionResult.portfolios`, and existing Portfolio
serialization as the application entry points. Extend existing presentation
helpers only where the consumer genuinely lacks access. Add clear examples for
one and several candidates, classifications, crossmatches, photometry, reported
counts, and execution provenance.

The consuming bridge must select the correct candidate portfolio before extracting
records. An explicit object-ID argument must filter or validate that identity;
it must never relabel records collected from several objects. Preserve survey
identity and channel/producer qualifiers. Select classification records using
declared time/classifier/version rules; do not assume list order means newest.

Keep ordinary/forced photometry and non-detections distinguishable. Provide
DataFrame projections as views over Portfolio, without introducing nucleuswatch's
`BrokerResult` into Alertissimo's domain model. Preserve execution provenance even
when a particular consumer chooses to display fewer fields.

Keep changes to the actual nucleuswatch bridge in Bibin's repository as a proposed
follow-up; this series can supply a minimal consumer example and regression
fixtures inside Alertissimo. No write access to his repository is assumed.

Add `tests/test_application_portfolio_access.py` and a small example under
`examples/`. Document the stable supported access route and avoid exposing more
internal planner/binder APIs merely for the example.

```bash
python -m pytest -q tests/test_application_portfolio_access.py tests/test_portfolio_lightcurve.py tests/test_portfolio_serialization.py tests/test_dsl_public_api_serialization.py tests/test_target_bound_partition_identity.py tests/test_api_continuation.py
```

### PR 09 — Reference workflow and acceptance handoff

Add `docs/discovery_integration.md`, the eight-provider/survey support matrix, and
the material inventory from PR 07. Include runnable DSL examples only after their
syntax and semantics are verified by the public API. Keep the original three
reports as named regressions. Attribute Bibin's report and link nucleuswatch;
describe it as an external reference application, not as an endorsed scientific
classifier or an Alertissimo dependency.

Provide at least these named recorded-response cases:

- `alerce-classification`: unconstrained and named-classifier lookup.
- `fink-class-time`: the exact seven-day SN-candidate query.
- `discovery-filter-retrieve`: discovery, a mapped residual selection, and
  light-curve/classification retrieval for surviving candidates.
- `multi-object-consumer`: at least two object IDs with distinct photometry and
  classifications, proving that extraction does not mix them.
- `empty-window`: valid complete discovery with no matching candidates.
- `incomplete-window`: saturated or interrupted discovery remains explicit.
- `provider-discovery-matrix`: each activated provider/survey combination plus
  representative explicitly unsupported combinations.

Compare direct broker parsing and Alertissimo normalization using identical
recorded upstream responses. Compare scientific values, ownership, units, and
missingness; do not compare generated internal IDs or JSON list order byte for
byte. If the two selection implementations differ, explain the reason rather
than force equality by weakening Alertissimo's semantics.

Add `tests/test_discovery_integration_acceptance.py`. Also add
`scripts/live_dsl_discovery.py` with this planned interface:

```text
--list
--validate-only
--scenario NAME        repeatable; names listed by --list
--start ISO_DATETIME   paired with --stop for fixed-window comparisons
--stop ISO_DATETIME
--output-dir PATH      serialized results and a concise diagnostic summary
```

The script must call the public facade, not reconstruct the backend. Default
windows should be modest and limits visible. It should load existing credential
names, classify PASS/FAIL/UNAVAILABLE/SKIP, and record input DSL, resolved bounds,
revision, dependency versions, result identities, counts, and endpoint provenance.
It must not claim that a successful truncated search establishes completeness.

These commands become valid once PR 09 adds that script:

```bash
python -m pytest -q tests/test_discovery_integration_acceptance.py
PYTHONPATH=. python scripts/live_dsl_discovery.py --list
PYTHONPATH=. python scripts/live_dsl_discovery.py --validate-only
PYTHONPATH=. python scripts/live_dsl_discovery.py --scenario alerce-classification --scenario fink-class-time --scenario discovery-filter-retrieve --output-dir .local-output/discovery-integration
```

Use the script's paired `--start` and `--stop` options for a fixed historical
comparison only where the provider matrix confirms those semantics. Record the
chosen actual dates in the handoff; do not use permanently fixed dates for every
future live test. Preserve the seven-day relative example as its own regression.

## Verification and merge discipline

All application tests and live provider calls for this implementation series run
on Veljko's machine. This document adds no implementation and claims no planned
test has passed. Do not install the entire stack in a document-editing session.

For each PR:

1. Rebase the work onto current `main` and implement only the named boundary.
2. Add focused regressions for changed contracts and meaningful failure cases.
3. Run its focused commands locally and record the exact outcome.
4. Run `git diff --check`; review declarations, payload evidence, and package/CI
   inclusion when adding runtime files or resources.
5. Include the commands and any live limitation in the PR description. A missing
   token or upstream outage is not a passing live result.
6. Merge, update `main`, and create the next branch. Keep the plan's progress table
   current with PR numbers and resulting commits.

After the relevant provider milestones, run the existing facade checks:

```bash
PYTHONPATH=. python scripts/live_dsl_api.py --validate-only
PYTHONPATH=. python scripts/live_dsl_api.py
PYTHONPATH=. python scripts/live_dsl_facade_acceptance.py --scenario dsl-classification-reuse --scenario dsl-cross-provider --scenario dsl-filter-candidate-flow
```

Lasair's existing Alertissimo scripts use `LASAIR_ZTF_TOKEN`; nucleuswatch's
`LASAIR_TOKEN` is not automatically the same environment-variable contract.
Use each project's documented names. Do not put credentials in examples or
committed evidence.

After the series, run one broader offline sweep and the final live handoff:

```bash
python -m pytest -q
PYTHONPATH=. python scripts/live_dsl_facade_acceptance.py
PYTHONPATH=. python scripts/live_dsl_discovery.py --output-dir .local-output/discovery-integration-final
```

The new discovery suite should be offline by default under pytest. Live execution
remains an explicit script invocation. Audit existing test configuration before
the broader sweep so a default test run does not unexpectedly contact providers.

## Completion criteria

The series is ready for Bibin to test when:

- The two ALeRCE classification examples and the Fink class/time example have
  passing recorded-response regressions and successful local live evidence where
  upstream services are available.
- Supported searches validate, plan, bind, execute, and normalize through the
  public facade. Deterministically unavailable forms have honest diagnostics.
- The support matrix covers all eight existing provider/survey contracts and
  clearly separates activated behavior from deferred variants.
- Required reference-workflow fields have correct meanings and units, or are
  explicitly listed as external/deferred. Missing cutouts or host inputs are not
  hidden by claiming full application coverage.
- Search limits, partial responses, empty results, candidate identity, and
  downstream retrieval are exercised.
- A multi-object consumer obtains each candidate's own photometry and evidence.
- The guide provides reproducible commands and enough provenance to investigate
  differences without reconstructing the execution manually.

Notify Bibin once PRs 01–03 are ready if useful; there is no need to wait for all
provider expansion before offering a working class/time query. The final handoff
can follow after all PRs in the series are finished.

## Collaboration handoff after implementation

Send Bibin the merged baseline, guide, support matrix, and live examples. Ask him
to run the same application workflow using (a) his direct acquisition path and
(b) Alertissimo discovery/retrieval/normalization, then feed both into his existing
analysis and presentation.

Ask for concrete differences in candidate IDs, photometry and coverage,
classification records, contextual fields, failures, completeness, and runtime.
Recorded-response comparisons establish normalization parity; close-in-time live
comparisons reveal operational differences but cannot assume the services return
an unchanged stream.

Invite issues or a focused bridge PR through his fork. Repository collaborator
permissions are not required. Do not require him to abandon his adapters, promise
scientific coauthorship, or imply that current integration proves his scientific
claims. Let further collaboration follow the work actually done.

## Outside this series

Leave richer broker-comparison UI, universal consensus policies, new aggregate
DSL operators, TDE ranking, scheduling, notification infrastructure, host-catalogue
harvesting, and Zooniverse publishing for subsequent work. Existing confirmation,
matching, continuation, and scientific derivations must keep working, but they do
not need redesign for this series.

## Progress

| PR | Branch suffix | PR number / commit | Local verification | Live outcome |
| --- | --- | --- | --- | --- |
| 01 | alerce-classification | [#293](https://github.com/sambolino/alertissimo/pull/293), main `1673fa0` | User confirmed successful verification | Not separately reported |
| 02a | predicate-bindings | [#294](https://github.com/sambolino/alertissimo/pull/294), main `7f7165d` | Merged; local results not separately reported | No provider activation |
| 02b | time-bindings | [#295](https://github.com/sambolino/alertissimo/pull/295), main `d91106e` | All three CI workflows passed; local results not separately reported | No provider activation |
| 03a | fink-result-limit | Prepared on `feat/discovery-03a-fink-result-limit`; PR pending | Not run here; local handoff | No broker calls; semantic discovery pending |
| 03b | fink | Pending; after 03a merge | Pending | Pending |
| 04 | alerce | Pending | Pending | Pending |
| 05 | lasair | Pending | Pending | Pending |
| 06 | antares | Pending | Pending | Pending |
| 07 | required-material | Pending | Pending | Pending where applicable |
| 08 | result-access | Pending | Pending | Through acceptance |
| 09 | acceptance | Pending | Pending | Pending |

## References

- [Alertissimo baseline](https://github.com/sambolino/alertissimo/tree/7dcff34ecc7320afd1fcd97247d60abe1fde6c61)
- [Nucleuswatch reference snapshot](https://github.com/bibinthomas123/nucleuswatch/tree/f0b4ee7fff4db6faf508d01e5b8b0311f0e3d52d)
- [Bibin's Alertissimo integration notes](https://github.com/bibinthomas123/nucleuswatch/blob/f0b4ee7fff4db6faf508d01e5b8b0311f0e3d52d/docs/alertissimo.md)
- [Fink class-search documentation](https://doc.ztf.fink-broker.org/services/search/classsearch/)
- [ZTF alert schema and field units](https://zwickytransientfacility.github.io/ztf-avro-alert/schema.html)

Recheck upstream contracts when implementing each provider branch. The linked
documentation may evolve after this baseline; captured payloads and verified
signatures should accompany the actual implementation.
