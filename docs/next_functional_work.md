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
Item 7 now implements ALeRCE/ZTF and ANTARES/ZTF detection-scoped completeness
with g/r delivery, plus Lasair/ZTF with g/r/i delivery. The approved loader amendment
stores immutable delivery metadata on existing RecipeCalls; other routes retain open completeness until audited.

With admitted material, witnessed lower bounds (`count >= N`), `min < x`
and `for any` work with open completeness. Exact counts, `count = 0`, `min > x`
and `for every` failing only on a short band remain unknown until a route establishes
collection completeness. The three audited ZTF detection subsets are now the
scoped exceptions; mixed nonempty totals and extrema stay open. Known contradictory
witnesses can still disprove a claim.

**Completed scope:** the [agreed contract](dsl_collections.md) is implemented in
existing semantic-model, expression/IR, evaluator and planner owners. Count/min/max,
any/every, exact NOT duality, serialization, continuation and compatibility have
accepted regressions. The instruction accounting records each requirement's status.
Use `{filter}`/`{output}`, relative paths and `where for …: (...)`; no second variable
notation or ordinary-case aliases were introduced.

**Remaining work:** initial collections with latest or without guaranteed material
remain item 4a; collection confirm is explicitly out of scope. Exact last-limit/
first-detection comparisons require reviewed filtered extrema/correlation (items
6/10); general flux/error significance multipliers require reviewed scalar
arithmetic or eligible supplied S/N (item 6). The [supported idioms and limits](dsl_collections.md#measurement-and-forced-photometry-idioms)
keep these outside runnable claims. Optional pairwise aliases remain item 10;
on-demand FP computation remains item 11. Item 7's acquisition/status/completeness
scope is complete, with the explicit open populations recorded there.

## 7. Measurements, non-detections and lightcurve boundaries

**Status: complete for the agreed acquisition, status and scoped-completeness work.**
The [instruction accounting](dsl_collections.md#item-7-instruction-accounting) records
implemented requirements, evidence and explicit deferrals. This does not establish
survey completeness or fresh live-provider acceptance.

**Current:** `with measurement` lowers to `GetMeasurementStep`/`get_measurement`
and has declared acquisition recipes for all eight pairs. New workflows use
`dsl_version: 3`; version-1/2 workflows still load and retain their version, but
cannot acquire the new operation through implicit continuation upgrades.
Provider lightcurve retrieval plans on all pairs; local `LightcurveStep` construction
explicitly remains unimplemented. Ordinary upper-limit flag mappings now cover
all eight pairs on measurements and existing lightcurve points: ALeRCE/ZTF uses
the source array, Lasair/ZTF uses non-null `candid` before `diffmaglim`, Fink/ZTF
uses `d:tag` (`badquality` remains unknown), ANTARES/ZTF uses `ant_survey`, and LSST
DIASource rows are detections. Forced-only epochs acquire no ordinary status.
Lasair/ZTF detection-only values use a same-row guard to prevent copied rich-format
limit values from becoming PSF measurements. No route completeness is enabled by
these flag mappings.

**Acquisition sources (27 November 2026):** existing endpoint/mapping contracts and
the saved fixtures establish these choices, not collection completeness.

| Pair | Measurement route | Source evidence |
|---|---|---|
| ALeRCE/ZTF | `query_lightcurve`; optional `query_forced_photometry` | `tests/fixtures/alerce/ztf/query_lightcurve.json`: both detections and non-detections, whereas `query_detections.json` contains only detections. |
| ALeRCE/LSST | `query_lightcurve`; optional `query_forced_photometry` | Corresponding LSST fixtures supply DIASource rows and bundled forced epochs; the separate forced endpoint is already mapped to measurements. |
| Fink/ZTF | `objects` with `withupperlim: true` | `objects_withupperlim.request.json` and response in `tests/fixtures/fink/ztf/`: 14 valid and 19 upper-limit rows. The endpoint contract says the option also includes bad-quality rows, whose status stays unknown. |
| Fink/LSST | `sources`; optional `fp` | `tests/fixtures/fink/lsst/sources.json` and `fp.json`: ordinary DIASources and separate forced measurements. |
| Lasair/ZTF | `lightcurves` | Maintainer's `ZTF23aamxeqf` object/lightcurves captures each contain 21 candidate/limit rows; the lightcurves mappings also supply guarded PSF measurements. Existing object-candidate magnitude debt is unchanged. |
| Lasair/LSST | `object`, `diaSourcesList` | Existing object fixtures and mappings retain DIASource rows and the separately named forced-source array. |
| ANTARES/ZTF | `get_by_ztf_object_id`, `locus_alerts` | Saved locus plus `alerts.json` contains 316 authoritative alerts; the 280-row secondary client lightcurve is not substituted. |
| ANTARES/LSST | `get_by_lsst_dia_object_id`, `locus_alerts` | Saved locus plus `alerts.json` supplies the LSST DIASource properties used by measurement mappings. |

Optional calls retain the lightcurve policy, including omission of a singular
optional call when a dependency's target population is not yet known. Required
calls still fan out through the binder. Plain lookup/lightcurve recipes are
unchanged. No-route measurement requests name the broker and fail admission;
incidental observation predicates do not silently gain history calls. Existing
mapped records/products remain distinct in material views; point arrays and
measurement records are never pooled into one count.

For example, this requests the existing broker history before selecting objects
with a witnessed detection in g:

```text
object ZTF23aamxeqf from ztf via lasair
with measurement
filter count(measurement@ztf:lasair where photometry.g.upper_limit = false) >= 1
```

This counts measurement records, not distinct upstream observation identities;
the existing collection contract still requires a reviewed identity rule for
distinct counting. Material history is preserved rather than deduplicated by a
guessed scientific key.

**Component acquisition:** `with <product>.<component>` and reference-driven
promotion are implemented in version 3 through the existing IR/resolver. Only
calls in that product's own recipe are promoted, with no declaration edits.
Qualified requirements retain origin/producer/broker scope. Empty successes retain
objects; explicit empty collection receipts can prove zero without closing a
nonempty history or introducing result fields. Missing/malformed payloads and
normalization loss stay unknown. Sibling arrays stay separate and competing arrays
remain ambiguous. See [the component rules](dsl_collections.md#required-components-and-references).
Completed prefixes are immutable: a later unguaranteed reference keeps the material
error; an explicit new component retrieval may reuse identical prior required
calls, but cannot treat an optional prior call as guaranteed. Plain plans and
version-1/2 wire formats are preserved; component metadata requires version 3.

**Lasair/ZTF forced photometry:** object and lightcurves payloads map the captured
688 forced epochs into `lightcurve.forced_photometry_points`, separate from ordinary
points. Flux/error retain native DN through unit-neutral paths; calibration reuses
`<calibration>(L1)` with its zero point in mag. No magnitudes are derived. Missing
`-99999` flux/error values stay unavailable; genuine negative fluxes remain signed.
`ranr`/`decnr` remain nearest-reference-source coordinate debt, without a new branch.
Required empty child arrays are proved against their declared parent object IDs;
missing/malformed children or omitted parents do not prove zero. Two separately
retrieved series retain the existing product-ambiguity rule. Capture provenance and
sources are in the [fixture notes](../tests/fixtures/lasair/README.md).

**ZTF detection completeness:** ALeRCE `query_lightcurve.detections`, Lasair
`lightcurve_candidates` and ANTARES `locus_alerts` use their existing material
proofs on required identity-bound acquisitions. Counts close only when their
condition entails `upper_limit = false`. Every raw row must be accounted for by
source-indexed measurements; matching detection points retain the same mapped
fields, time and known status. Lasair batches require exactly the requested parent
IDs and preserve global row indices. Bad/omitted rows and contradictory identities
withhold closure. Materialized ANTARES Alerts are used; proof inspection never
invokes lazy getters or substitutes the secondary client lightcurve.

Delivery is declared separately: g/r for ALeRCE and ANTARES, g/r/i for Lasair,
backed by existing captures. Fully covered empty histories can prove zero in
those delivered detection bands without fabricating product records. No whole
nonempty mixed-array, extrema or measurement completeness is asserted. LSST lacks
the matching material time proofs and remains open.

**LSST availability:** audited Rubin schemas v8.0–v11.2 have no separate
non-detection-limit records. Ordinary LSST points are DIASource detections; forced
photometry supplies below-threshold evidence. Alert-delivered precovery becomes
available after discovery, so pre-discovery history depends on retrieval time.
ALeRCE/LSST retains both forced-only measurements and detection rows with own-epoch
forced values; their branches and the separate forced-point product stay distinct.

**Explicit deferrals:** local `LightcurveStep` construction remains unimplemented
because this work does not need it. LSST and measurement completeness remain open,
as do nonempty mixed-array totals and extrema. Temporal correlation and general
significance arithmetic remain reviewed DSL extensions under items 6/10; on-demand
photometry services remain item 11. Point display controls remain item 8 and never
change acquired evidence. The runtime audit can still withhold closure for an
individual response; route support never overrides unknown evidence or failure.

The [route accounting](dsl_collections.md#detection-completeness-first-route) records
the current enabled and open populations. Any additional YAML structure beyond the
approved delivered-band declaration still needs review.

**Delivered boundary:** explicit measurement intent, attributable ordinary/forced
status and values, general component requirements, and audited detection-count
completeness through existing owners. Incidental evidence, product distinctions
and shared presentation remain intact. No additional operation or local lightcurve
builder is authorized by closing this item.

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
temporal ordering and units then. Exact last-limit/first-detection selection also
needs a reviewed filtered-extrema or correlation design; the current aggregate-to-
aggregate comparison prohibition stays in force. Do not complicate ordinary
one-element predicates or imply that a new binder alone implements that query.

## 11. On-demand forced-photometry services — deferred

**Current:** existing FP retrieval uses the component rule in item 7.
Programmatic `GetForcedPhotometryStep` remains available; public
`with forced_photometry` remains outside the Portfolio noun gate. Plain recipes
can include optional FP calls; ALeRCE/LSST also returns bundled FP.

**Later decision:** requests that trigger new computation, such as IPAC ZTF or an
on-demand broker run. Item 7 retrieves existing data only; no service invocation,
new FP noun/record or automatic computation is introduced by the component rule.
