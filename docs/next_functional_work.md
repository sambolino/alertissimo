# Next functional work

Implementation IDs are stable references, not a fixed PR count or merge order.
Split later work as 4a/4b without renumbering unrelated items. Architecture belongs
in [ARCHITECTURE.md](../ARCHITECTURE.md); only implementation items are numbered here.

Milestone notes were removed in this PR and remain available in Git history before its commit.

Goal: a deploy-yourself beta with UI and deterministic DSL, without NLP. Maximize
semantically covered broker diversity. Coarse classification, native headline selection,
catalogues and discovery/selection are required work; cutouts come last.

Current-state notes were checked on main `b7f9905` (7 November 2026): public offline
planning, relevant source/fixtures, focused regressions and a clean installed wheel.
They are not fresh live acceptance. Items 1–2 and 6 record later accepted merges;
other provider/UI states retain that audit baseline until explicitly rechecked.
Recheck the current revision before coding.

## 1. Coarse classification normalization

**Decision taken (13 November 2026):** use the ELAsTiCC hierarchy plus the reviewed
local moving-source extension, code-set aliases and three-valued ancestry comparison.
See the approved strict tuple IR amendment in the headline policy.

**Current:** the reviewed finite headline policies are connected to immutable
material views, normalized predicates and the comparison UI. Native outputs and
alternatives remain distinct. ANTARES native Superphot+/DeSoto retrieval is admitted,
with unresolved input scope/defaults explicitly abstaining. See the authoritative
[headline policy](classification_headline_policy.md) for defaults and limits.

**Accepted baseline:** merged in #355 after local/package validation and green CI.
Open scientific choices remain listed in the headline policy.
No cross-method probability ordering or new probability threshold is introduced. Catalogue labels without a reviewed candidate proposition
remain recognized context.

## 2. Native headline selection and normalized confirm

**Current:** separate `classification@headline:<broker>` records retain the selected
native labels/taxon code sets, policy digest, source method/version and input record IDs.
Confirm obtains each broker's full classification recipe and evaluates only its own
occurrence-local evidence. It counts each broker once; missing and incompatible
outputs do not become positive NOT votes. Native best queries remain compatible.
Continuation retains finalized prior views and pinned interpretations. Only new
eligible material permits a new interpretation; deserialization/UI do not remap.

**Accepted baseline:** merged in #355 after counterexample and CI validation:
method precedence, composed confirmation, immutable continuation, visible unknown-label
abstentions, input scope and initial filtering before latest. Further changes to
selection policy require a new decision; continue with the remaining work items.

## 3. Catalogue crossmatches and field coverage

**Current:** all eight pairs have mappings/debt ledgers and existing audit tooling.
Coverage remains partial. Fink and ANTARES have targeted retrievals; ALeRCE has no
admitted crossmatch Get. Lasair has mappings/recipes but generic public requests
are ambiguous; ZTF targeted TNS is also ambiguous, while LSST targeted TNS plans.

**Target/work:** follow [field coverage](provider_field_coverage.md). Map every
scientifically established field possible, correct existing mappings, resolve
uncertain units/identity/scope, preserve provenance and discuss genuinely missing
concepts. Revisit existing intentional debt rather than count bookkeeping as done.
Resolve real route/target selection; do not drop crossmatch from enrichment to
hide failure. Preserve ANTARES catalogue classes and Sherlock contextual meaning.

**Completion:** accounted-for audited fields with evidence and dispositions;
ownership/unit regressions; executable admitted public requests. Neither zero
unaccounted leaves nor a provider-wide mapping proves exhaustive coverage.

## 4. Semantic discovery

**Current:** unwindowed cones and lookup plan for all eight pairs. Semantic routes
are uneven: ALeRCE supports object/class/selected-summary search; Fink/ZTF has eight
audited ordinary class-index labels; Lasair/ZTF has selected numeric conjunctions
and Sherlock equality; ANTARES/ZTF requires scoped coordinate predicates. Generic
Fink/Lasair/ANTARES LSST lowering is absent.

**Target/work:** expand verified semantic translations and equivalent complete
local evaluation. Use actual native required inputs, fields, identity and population
contracts. Preserve whole initial predicates and local residual checks. Do not add
raw SQL/Elasticsearch escape hatches or broker switches in planner/UI code.

**Completion:** per-pair/route supported populations and conditions, native/local
equivalence and actual public execution evidence. A working cone is not a class
scan. See the [discovery baseline](discovery_integration.md).

## 5. Uniform temporal selection and global latest

**Current:** all modes/latest plan on admitted ALeRCE/ZTF and Lasair/ZTF routes;
ANTARES/ZTF supports its scoped coordinate route but not native temporal cone/
latest. Fink/ZTF admits default within on its eligible class route, not first/last/
latest or temporal cone. All four LSST pairs lack admitted temporal/latest proof.

**Target/work:** identical within/first/last/latest meanings everywhere, with native
or sufficient complete local evidence. Default within needs an ordinary detection
in the closed interval; first/last test actual extrema. Latest ranks the complete
qualifying object population after the whole initial condition. Verify UTC/TAI,
history, object recency, identity, pagination and saturation. Keep survivors' full
returned histories; later filter does not refill.

**Completion:** per-pair/route composition and completeness evidence, or a reviewed
concrete upstream limitation after investigating alternatives. Missing mappings/
recipes remain our implementation gaps; a new deferral alone is not completion.
No first-page sorting, silent window shrinking, dropped conditions or alert-order
substitution. Script `--window-hours 24` is not a DSL cap.

For a closed [59010,59011] window: A=[59009,59012] does not satisfy within;
B=[59010.5,59020] and C=[59010.7,59011] do. Latest 1 among B/C is B using overall
object recency. If another initial predicate excludes B, C must be considered
before ranking. An upper limit inside the window is not a detection witness.

## 6. Collection DSL

**Accepted baseline:** syntax/IR #359, evaluation #360 and admission #361 are
merged after maintainer-run checks and CI. Scoped nodes, multiline coordinates,
count/extrema ranges, Kleene quantifiers, branch membership and ambiguity warnings
are connected to later filters over guaranteed preceding material. Version-2
continuations preserve the immutable prefix and scientific diagnostics; acquisition
warnings still block continuation. Later filtering does not refill latest.
Surface and canonical guards name item 4a for initial collection/latest and missing
material, and reject collection propositions in confirm. This is offline regression
acceptance, not a new live-provider acceptance claim.
Delivered-band declarations are deferred to the first per-route collection-
completeness slice under item 7; recipes and capability files remain untouched.
Closed-bound logic has synthetic test proofs only.

With admitted material, witnessed lower bounds (`count >= N`), `min < x`
and `for any` work with open completeness. Exact counts, `count = 0`, `min > x`
and `for every` failing only on a short band remain unknown until a route establishes
collection completeness. Known contradictory witnesses can still disprove a claim.

**Completed scope:** the [agreed contract](dsl_collections.md) is implemented in
existing semantic-model, expression/IR, evaluator and planner owners. Count/min/max,
any/every, exact NOT duality, serialization, continuation and compatibility have
accepted regressions. The instruction accounting records each requirement's status.
Use `{filter}`/`{output}`, relative paths and `where for …: (...)`; no second variable
notation or ordinary-case aliases were introduced.

**Remaining work:** initial collections with latest or without guaranteed material
remain item 4a; collection confirm is explicitly out of scope. Actual completeness
and scientific field coverage remain item 7. Optional pairwise aliases remain item
10, and FP surface/policy remains item 11. None is silently included in completion.

## 7. Measurements, non-detections and lightcurve boundaries

**Current:** `with measurement` is ontology-valid but lacks retrieval lowering.
Provider lightcurve retrieval plans on all pairs; local `LightcurveStep` construction
explicitly remains unimplemented. Ordinary upper-limit flag mappings now cover
all eight pairs on measurements and existing lightcurve points: ALeRCE/ZTF uses
the source array, Lasair/ZTF uses non-null `candid` before `diffmaglim`, Fink/ZTF
uses `d:tag` (`badquality` remains unknown), ANTARES/ZTF uses `ant_survey`, and LSST
DIASource rows are detections. Forced-only epochs acquire no ordinary status.
Lasair/ZTF detection-only values use a same-row guard to prevent copied rich-format
limit values from becoming PSF measurements. No route completeness is enabled by
these flag mappings.

**Agreed 27 November 2026; remaining implementation:** add the approved
`get_measurement` operation/recipes, then product-component requirements and
reference-driven promotion within existing retrievals, preserving plain plans.
Reuse `<calibration>(L1)` on forced-photometry points for Lasair instrumental flux
and its separate zero point; derive no magnitudes. Keep `ranr`/`decnr` as defined
nearest-reference-source coordinate debt, without adding a branch. These changes
are approved but not yet runnable. Local `LightcurveStep` remains deferred.

**Target/work:** define measurement acquisition using concrete source/scope examples
and a reviewed canonical mapping. Map true/false limit flags where native evidence
establishes them; retain unknown otherwise. Missing flux alone is not non-detection,
nor is a detection's limiting depth another observation.

**Per-route collection completeness:** establish evidence on the existing path,
starting with detection-only arrays that exactly match an existing temporal proof.
A detection-history proof does not close a whole mixed array. The approved next
slice may close a count only when its condition entails `upper_limit = false`
and its population is covered by the audited proof payload and normalization.
The first proven route also introduces its delivered-band declaration and the
approved existing-loader support. Keep incidental measurement counts open until
acquisition/completeness is defined.

**Completeness entry audit after #361:** the checked material-history routes do
not yet supply an eligible detection-only `points` array. ALeRCE/ZTF maps both
`query_lightcurve.detections` and `query_lightcurve.non_detections` into `points`.
ANTARES/ZTF maps `locus_alerts`, including the explicit upper-limit discriminator,
into `points`. Lasair/ZTF maps `lightcurve_candidates`, where existing guards/tests
allow limit-only rows, into `points`. Their detection proofs cannot be applied
unchanged to these whole arrays. See [the source-backed audit](dsl_collections.md#first-completeness-route-entry-audit).
This is a current implementation boundary, not an upstream impossibility claim.

Before implementing the first closure, audit required-call success, payload and
identity coverage, and raw-row-to-element normalization, including omitted or
invalid rows. Derive the link from the existing proof payload and status mappings;
any additional YAML structure needs review. LSST and measurement completeness
remain open. Delivered-band metadata alone does not resolve the evidence boundary.

**Completion:** executable supported measurement intent and reliable field semantics,
preserving incidental evidence, distinct products and shared presentation. Do not
add an operation beyond the approved `get_measurement`, or add a local builder.
FP component requests are approved for a later slice; on-demand computation remains
item 11. Default visibility/composition choices remain open.

## 8. Deployable UI

**Current:** investigation ID/basic cone forms use saved normalized evidence; DSL
mode executes live. Validation-only and upload/replay viewers also exist. A clean
installed wheel fails investigation startup through `scripts.build_ui_fixtures`;
the DSL editor HTML asset is absent. Shared scientific extraction is already fixed.

**Target/work:** intended live ID/cone controls use the existing deterministic
pipeline; keep demos/replays/uploads explicit. Remove development-only startup
dependencies, package actual assets, provide a reproducible installed launch path
and preserve visible-result continuation. Keep reported detections, loaded points,
products, quantity/kind/limits and evidence outcomes distinct.

**Completion:** clean installed startup, actual component/browser interactions,
critical live/replay/continuation flows and scientific boundary checks. No replacement
framework or hosted session/database/service architecture.

## 9. Cutouts — last required feature expansion

**Current:** Fink/ZTF object-centric `data_product` plans. ALeRCE products lack mapped
material; Fink/LSST is alert-targeted; Lasair/ANTARES have no admitted product Get
in the checked contract.

**Target/work:** investigate verified native stamps/image links/thumbnails and
ownership after higher-priority work. Reuse existing data-product structures/enums.

**Completion:** truthful admitted routes, normalized products, shape/ownership and
failure evidence. Do not add `with cutout` or new record containers for enum values.
This plan does not add a spectrum programme.

## 10. Optional element bindings — deferred

**Current:** no named collection binders, self-joins or correlated collections.

**Later decision:** reevaluate `as p` only for multiple element scopes, such as paired
points or an FP measurement near each outer point. Review scope, distinctness,
temporal ordering and units then. Do not complicate item 6's ordinary cases.

## 11. FP surface and acquisition policy — deferred

**Current:** programmatic `GetForcedPhotometryStep` exists; public
`with forced_photometry` fails the Portfolio noun gate. Lightcurve recipes can
include optional FP calls; ALeRCE/LSST can also return bundled FP.

**Later decision:** explicit FP intent, required versus incidental evidence,
lightcurve composition and the existing Step together. No new FP noun/record,
broader component admission, or automatic-supplementation change is approved.
