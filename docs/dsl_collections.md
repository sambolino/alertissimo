# Collection expression contract

Agreed design with D3 decisions fixed on 13 November 2026. **Syntax/IR #359,
evaluation #360 and admission #361 are accepted after maintainer-run checks and CI.**
The existing validator/planner prove call-scoped material availability; execution
uses the existing normalization evaluator. This acceptance covers the stated
admitted placements and guards, not fresh live-provider acceptance. No route yet
establishes collection completeness.
This owns the language contract for [implementation item 6](next_functional_work.md#6-collection-dsl).
It does not create another query engine or authorize deferred FP policy.

## Canonical forms

```text
where count(measurement@ztf:fink
            where quality.real_bogus > 0.9) >= 5
```

```text
where for every {filter}: (
    count(lightcurve.points
          where photometry.{filter}.psf.mag exists
            and photometry.{filter}.upper_limit = false) >= 5
)
```

```text
where for every {filter} in [g, r]: (
    count(lightcurve.points
          where photometry.{filter}.psf.mag exists
            and photometry.{filter}.upper_limit = false) >= 5
)
```

```text
where for any {filter}: (
    min(lightcurve.points.photometry.{filter}.psf.mag) < 19
)
```

```text
where for any {output}: (
    classification.assessment.{output}.probability >= 0.8
)
```

The last threshold is a query example, not a classifier acceptance policy.
Magnitude examples do not imply automatic conversion of flux-only/negative values.
`max(<projection path>) <op> <number>` is admitted by the design symmetrically
with `min`. Quantifiers may nest, but an inner parameter may not shadow an outer
one. Parenthesized bodies/aggregate arguments may span lines with `#` comments;
indentation is cosmetic and error coordinates must refer to the original text.

An admitted example is a later filter over requested material:

```text
objects ZTF20aaaaaaa, ZTF20bbbbbbb from ztf via alerce
with lightcurve via fink
filter for every {filter} in [g, r]: (
    count(lightcurve@ztf:fink.points
          where photometry.{filter}.psf.mag exists
            and photometry.{filter}.upper_limit = false) >= 5
)
```

This selects only established true candidates. Five g and five r witnesses suffice;
a short band remains unknown without completeness and does not select. Native
fields without a guaranteed preceding mapping/retrieval remain deferred to item 4a.
The earlier `where` examples state expression semantics; initial admission depends
on the scheduling rules below.

## Scope and domains

- Reuse ontology path parameters. Do not introduce `$band`, bracketed variable
  lookup or `as p` for an ordinary one-element predicate.
- Collection boundaries come from ontology array declarations. Relative paths in
  a collection `where` refer to that same element, not nearby Portfolio records.
- Work within the current candidate's material view, not across candidates or all
  historical snapshots. Preserve producer/channel qualifiers and output-local
  label/metric association.
- `{filter}` defaults to the candidate origin's declared filters; observed bands
  are not a substitute. `in [g, r]` restricts that domain deliberately.
- Other parameters share binding mechanics but need scoped domains. `{output}`
  refers to the relevant producer/model/container, not unrelated global outputs.
- Declare missing metadata in existing semantic/provider owners. Require an
  explicit domain or report an unresolved one instead of inventing a default.
- Parenthesized bodies delimit `for …:`; indentation remains cosmetic. Preserve
  existing scalar, existence and Boolean forms.

## Counting, projection and evidence

### Required components and references

```text
object ZTF18abbuksn from ztf via alerce
with lightcurve.forced_photometry_points
```

This requires the producing calls in the lightcurve recipe and keeps an object
whose calls succeed with empty arrays. It does not select objects with FP. To
select those that actually have it, use either:

```text
object ZTF18abbuksn from ztf via alerce
with lightcurve where forced_photometry_points exists
```

```text
object ZTF18abbuksn from ztf via alerce
with lightcurve
filter count(lightcurve@ztf:alerce.forced_photometry_points where time.mjd > 60000) >= 1
```

The reference strengthens the existing retrieval; it does not create another Get.
Without guaranteed preceding material, admission still reports item 4a. Previously
admitted initial-where scheduling is retained for already guaranteed material;
an optional-only component cannot introduce implicit acquisition. A completed
continuation prefix is never strengthened retroactively. Request the component
explicitly in a new retrieval if the prefix did not guarantee it; identical earlier
required calls may be reused, while an earlier optional call is not a guarantee.

The same rule applies to other ontology components, including
`with measurement.forced_photometry` on ALeRCE/LSST. Every matching producer call in
that Get's own recipe becomes required. Another product's recipe cannot supply a
missing route. Unknown paths and no-route brokers are rejected. Plain requests
retain their recipe policy, including optional supplements and cardinality guards.

A successful required empty collection receipt can establish
`count(lightcurve.forced_photometry_points) = 0`. This is reconstructed from the
required calls, their explicit raw arrays and bound object identities. Missing,
null or malformed arrays and nonempty rows omitted during normalization do not
prove empty. No empty observation or product record is invented. This proof does
not close a nonempty history, a measurement record collection, or an unavailable
band. No delivered-band declarations are introduced here.

Sibling arrays returned in separate records of the same qualified product do not
compete for the named array: Fink/LSST `points` and `forced_photometry_points` remain
separate. Multiple records carrying the requested array, multiple qualified
products, and malformed competing arrays retain `ambiguous_product` handling.

`count` counts named collection elements. Records, values and distinct observations
are not interchangeable. One record containing ordinary and forced values is not
automatically two observations; neither may its measurement and lightcurve
representations be silently added together. Distinct counting needs a reviewed,
trustworthy identity rule.

Keep `lightcurve.points` and `lightcurve.forced_photometry_points` distinct. Scalar
paths crossing arrays project the values used by min; they do not silently apply
a quality/censoring policy. “Valid” requires explicit criteria or a reviewed named
rule; no universal `measurement.valid = true` is defined.

Known complete empty can count as zero; unavailable material cannot. Missing fields
and upper-limit flags remain unknown. Empty min has no fabricated numeric value.
Five established qualifying witnesses can prove at least five without proving
exactly five when further membership is unknown. None of this bypasses required
retrieval failures or current execution-policy completeness failures.

## D3 decisions

These are the agreed evaluator/admission contract. Syntax/IR represents and
validates the constructs. The existing normalization predicate evaluator now
implements their local evaluation. Workflow admission proves the material and
placement rules below without changing these scientific decisions.

1. **Counts are ranges.** For `count(C where P)`, L is the number of true members;
   U is L plus unknown members only when C is known complete, otherwise infinity.
   Absent material gives [0, infinity). A comparison is true when it holds for
   every integer in the range, false when it holds for none, unknown otherwise.
   Equality is true only for an exact singleton. Completeness must come from
   existing, applicable execution/selection evidence, never mere response success.
   Incidentally present measurement records retain open completeness (item 7b).
2. **Quantifiers use Kleene logic.** `any` is OR; `every` is AND. A true witness
   proves `any` despite unknowns; a false witness disproves `every` despite
   unknowns. Otherwise an unknown member leaves the result unknown. NOT must
   preserve `not every B = any not B` and its dual exactly.
3. **Empty domains.** Static `in []` is invalid and a declared domain is nonempty.
   Both quantifiers over an empty data-derived domain, including `{output}`,
   produce unknown, also under NOT. Express emptiness with existence/counts.
4. **Extrema are ranges.** A known minimum is an upper bound; unknown members or
   open completeness open its lower bound to minus infinity. Max is symmetric.
   A complete empty collection has no extremum and comparisons are unknown.
   Thus one 18.5 witness proves `min < 19`; proving `min > 19` needs a complete
   collection with all values known and above 19. No silent censoring/quality
   policy applies; a limit point without `psf.mag` contributes unknown to that
   projection.
5. **Projection membership is branch-local.** A point belongs to a filter only
   when its `photometry.<filter>` branch exists. A g point is not an r point;
   a missing leaf within an existing branch is unknown. In an element condition,
   a reference to an absent parameterized branch is false, preventing another
   band's point from contributing to the count.
6. **Declared and delivered bands differ.** The default filter domain is the
   origin's declaration (`ztf: [g, r, i]`, `lsst: [u, g, r, i, z, y]`) on
   `<photometry>.<{filter}>` in `ontology.yaml`. `in [...]` restricts it. A complete
   route delivering a band with no members gives [0, 0]; an undelivered band gives
   [0, infinity). Delivery must be declared per lightcurve route in the existing
   `capabilities.yaml`; undeclared routes make all bands unavailable. Observed
   bands never redefine the origin's domain or prove completeness. ALeRCE/ZTF and
   ANTARES/ZTF declare g/r delivery; Lasair/ZTF declares g/r/i.
   The existing recipe loader retains these as immutable call metadata.
   Delivery alone never closes a count.
7. **Bind one product.** An aggregate/quantifier collection selector binds one
   qualified product and named array per candidate, without pooling or first-match
   selection. Records carrying only sibling arrays do not compete for that array.
   Statically visible ambiguity requires an existing qualifier, for example
   `lightcurve@ztf:fink.points`. Multiple runtime records carrying the requested
   array produce unknown and a visible `ambiguous_product` diagnostic, not an exception. Never combine
   measurement records with lightcurve points into one count.
8. **Output scope is one classification record.** `every {output}` requires
   qualification to one producer. Multiple records/versions even after that
   qualification produce unknown plus `ambiguous_product`. Unqualified
   `any {output}` preserves the existing implicit any-record binding.
9. **Scalar compatibility.** Scalar predicates on multi-record nouns keep their
   existing implicit any-record meaning, including under NOT. Use counts or
   `every` for all/none; existing scalar, existence, Boolean, taxon and confirm
   semantics must not be reinterpreted.
10. **Language version.** No text marker is added. Newly constructed WorkflowIR
    defaults to integer `dsl_version: 3`; serialized IR missing the field loads
    as pre-collection version 1, including within a WorkflowRun. A runtime refuses
    a newer version. Scalar continuation preserves the existing version. Version
    2 remains sufficient for collection syntax; `get_measurement` and nonempty
    `required_components` require version 3. Neither version metadata alone asserts that a request is runnable.

## Representation and validation

The existing comparison keeps its `left`, `operator` and `right` fields. One side
may be an aggregate; the other must be a finite numeric literal. Aggregate-to-
aggregate/reference comparisons and aggregates inside existence tests are invalid.
A count condition uses explicit element-reference nodes, bound to its innermost
count. Absolute record references in that condition are rejected. Min/max require
a scalar-valued field below an array boundary; scalar fields may themselves have
uncertainty/metadata children in the ontology. Count requires an array or concrete
record collection.

Only `{filter}` and `{output}` are quantified. Parameters must occupy their ontology
scope, may not shadow an enclosing binding, and must be bound inside element paths.
Explicit restrictions are nonempty and duplicate-free and must belong to a declared
finite domain. Thus filter restrictions use the origin's declared filters; a named
`{output}` restriction currently fails validation because its domain is data-derived,
not a statically declared finite vocabulary. Unrestricted `{output}` remains valid;
`every` requires one producer-qualified classification selector.

All new expression/IR nodes are frozen and discriminated by `kind`. Canonical
workflow validation checks placement/scope even after JSON deserialization. Version
1 rejects all collection nodes, including those nested below Boolean/NOT predicates.
Collection references and relative leaves feed the existing material/headline
walkers. Native predicate realization leaves collection expressions residual.

## Evaluation boundary

The existing predicate owner exposes a three-valued internal result; its existing
Boolean callers still select only established `True`. Scalar assertion binding,
explicit absence and taxon comparisons retain their existing meaning. Collection
comparisons do not create provider parameters or retrievals.

The evaluator accepts transient explicit evidence keyed by
`(internal_record_id, exact_array_path)`, with completeness and delivered-band
values. A third key member, `detections`, restricts the evidence to count conditions
that entail `photometry.<filter>.upper_limit = false`; it never closes a mixed-array
total or an extremum. Required-component receipts separately prove explicitly empty
requested arrays, keyed by Portfolio identity and qualified array path. These
proofs are transient and add no Portfolio, StepRun or WorkflowIR fields. A fully
covered empty detection history can use a scoped Portfolio/qualified-array receipt
when normalization emits no point record; it proves zero only in delivered bands.
Missing/malformed arrays, normalization losses, summary counts and observed bands
do not establish completeness.

Competing array products or qualified classification versions yield unknown and
`ambiguous_product` messages in the existing StepRun `warnings`. Messages retain
candidate and selector identity even when selection removes that candidate, and
survive run serialization. Physical audit groups follow the material decision;
collection predicates are not re-evaluated against partial physical fragments.

## Scheduling and compatibility

Required initial predicate material precedes evaluation and global latest. A later
written retrieval cannot justify evaluation against missing material. Later
`filter` retains non-refilling semantics. Preserve continuation, serialization,
occurrence lineage and physical reuse.

Extend existing expression/IR, evaluation, planning and semantic metadata. New
functions/operators may be added, but existing canonical programs retain meaning.
Keep round-trip, unknown/evidence and compatibility examples suitable for NLP
training. Collection predicates always evaluate locally; never translate them to
provider parameters.

A later `filter` is admitted only when every candidate origin has guaranteed
preceding mapped material for the entire predicate. Required outputs are checked
per feasible route and authored projection; optional calls, endpoint-wide mappings
outside the route, future retrievals and another origin's fields are not proof.
Matching a bound `{filter}`/`{output}` path proves possible mapped material, not
that every branch or value is present. Missing values remain unknown at evaluation.
Classification method selection removes other methods from the material proof.

An initial collection `where` with `latest` explicitly reports deferred **item 4a**.
Without latest, an initial discovery predicate can use its required discovery-call
material; supplementary calls cannot supply its residual. Existing lookup lowering
may schedule an implied retrieval before its initial filter. Other placements
without guaranteed material also report **item 4a**. A later filter after latest
refines that already selected population without refilling it.

Collection propositions in `confirm` are rejected, including conditions attached
through `where` or a scoped material request. A bare confirm after an explicit
collection filter remains a separate existence question. Surface compilation and
canonical planning enforce the same boundaries.

Continuation uses its immutable canonical prefix, including inherited product
qualifiers; future products do not make an earlier filter ambiguous. Version-2
continuations admit collection filters when material is proven. A version-1
continuation refuses collection syntax explicitly and is not implicitly upgraded;
scalar continuation preserves its existing version. Existing StepRun warnings also
retain discovery-residual ambiguity before supplementary calls and finalization.
`ambiguous_product` is scientific abstention, not incomplete acquisition: immutable
continuation retains these diagnostics. Other acquisition warnings still prevent
continuation under the existing safety rule.

## Acceptance examples

| Evidence | Expected condition result |
|---|---|
| Six declared bands have counts 5,5,5,5,5,4 | Every-band at-least-five is false with completeness; unknown with open completeness. |
| Only g/r happen to arrive | Do not silently narrow the default domain; distinguish known empty and unavailable bands. |
| Explicit [g,r], each with five qualifying points | Other bands are outside this restricted query. |
| Bright limiting magnitude on an upper-limit point | Does not satisfy a predicate explicitly excluding limits. |
| Missing upper-limit flag | Does not automatically satisfy `upper_limit = false`. |
| Duplicate representations of an observation | No implicit observation double-count. |
| Initial collection predicate plus latest | Explicitly deferred to item 4a; no partial evaluation before ranking. |
| Equivalent later filter | Refine existing candidates without refill. |

Flag mappings follow explicit broker status; missing status stays unknown (item 7). Current grammar is
[`expression.lark`](../alertissimo/dsl/expression.lark); repetition/domain metadata
must be retained by the existing semantic-model owner.

## Detection completeness: first route

ALeRCE/ZTF `query_lightcurve`, Lasair/ZTF `lightcurves` and ANTARES/ZTF
`get_by_ztf_object_id` use their existing material detection proofs for the same
required, identity-bound history acquisitions. A temporal selection clause is not
required. Completeness is relative to the broker's holdings at retrieval time,
never to the survey. The ordinary `points` arrays continue to mix detections and
limits; only count conditions entailing `upper_limit = false` can close.

```text
object ZTF18abbuksn from ztf via alerce
with lightcurve
filter count(lightcurve@ztf:alerce.points
             where photometry.g.upper_limit = false
               and quality.real_bogus >= 0.8) = 2
```

The equality can be established when every relevant value is known. A missing
vetting value leaves that member unknown. Explicit negation and equivalent Boolean
forms retain Kleene semantics; an OR branch that admits limits prevents closure.

The runtime audit requires a successful required call, explicit history arrays,
one source-indexed normalized measurement per raw row, usable times and Boolean
status. The normalized detection points must match the measurement population's
times, bands and every shared mapped point field. Equal-time duplicates cannot
hide a lost row with different photometry or vetting. Mixed histories also account
for limit rows without extending the proof to their completeness. Contradictory
object IDs, missing/invalid status or time, unknown bands and dropped rows withhold
closure. Raw responses and normalized point records remain unchanged.

For batched Lasair responses every requested object must have exactly one declared
parent identity, with no unexpected parents and an explicit child array. Per-object
row indices retain their global positions in that physical response, including
when parent order differs from request order. Missing, duplicate or malformed
parents/children do not establish exact counts. Explicit empty children can prove
zero detections for delivered bands without creating an empty product record.

Receipt inspection reads mapping values or materialized public attributes only;
it does not invoke lazy relationship getters or make provider calls. Opaque or
unmaterialized history evidence leaves closure unknown. ANTARES native model
support therefore requires the actual Alerts array to be materialized, as in its
saved rich-Locus composite; a secondary client lightcurve is never substituted.

| Route | Delivery and accounting evidence |
|---|---|
| ALeRCE/ZTF `query_lightcurve.detections` | g/r; existing detection-only payload accounting and saved `query_lightcurve.json`. The combined point array also retains its non-detections. |
| Lasair/ZTF `lightcurve_candidates` | g/r/i; the [saved capture](../tests/fixtures/lasair/ztf/lightcurves_ZTF17aaabasp.json) has 1,404 mixed candidates with all three bands. All 10 point-field mappings share their measurement sources/transforms; parent IDs and raw-row indices are checked per batch. |
| ANTARES/ZTF `locus_alerts` | g/r; the [Alerts capture](../tests/fixtures/antares/ztf/alerts.json) has 70 detections and 246 limits. All 22 point-field mappings share measurement sources/transforms. Known `ant_survey` values and canonical g/R-to-g/r passband mappings delimit the detection population. |
| LSST routes | No matching material detection proof; completeness remains open. |

Mixed nonempty totals, limit-only counts, extrema and measurement-record counts
remain open. An observed band never supplies delivery metadata. ALeRCE and ANTARES
i-band counts remain unavailable for closed-bound claims; the origin's default
filter domain still includes i.

Do not split arrays, add result-model fields or broaden a temporal proof implicitly.
Delivery is validated for endpoint existence, the exact produced collection, and a
non-empty, duplicate-free subset of the origin's ontology filter domain. It never
establishes completeness by itself.

## Deferred extension

Named binders such as `as p` are reserved for later reevaluation of self-joins and
correlated nested collections (item 10). They must not replace the simple forms
above. On-demand FP computation is separately deferred in item 11. Broker-held FP uses
the required-component rule above.

## Completed instruction accounting

| Requirement | Status / owner of remaining work |
|---|---|
| Ordered arrays/items, parameter scopes, declared filters | Done in the foundation and syntax/IR; metadata unchanged by admission. |
| D3.10 versioning and JSON representation | Done in foundation/syntax. Admission preserves version 2 and explicitly refuses collection additions to version-1 continuations; no schema fields added. |
| Count/min/max/quantifier syntax and canonical nodes | Done in #359; local filter admission accepted in #361. |
| Parenthesized multiline, comments, source coordinates | Done in syntax/IR; grammar unchanged here. |
| D3.3 static empty restrictions, domain members and shadowing | Static checks done in syntax/IR; empty runtime domains remain unknown, including under NOT, in evaluation. |
| D3.7–8 product/output qualification and runtime ambiguity | Evaluation accepted in #360. Admission scopes static products to the occurrence/prefix and retains runtime warnings through facade serialization and discovery residuals. |
| Reference/material/headline walkers; no native pushdown | Done in syntax/IR. Material selection now controls collection audit projection without fragment re-evaluation. |
| D3.1–2 count ranges, quantifiers, exact NOT duality | Done in #360, including synthetic complete-evidence tests. Unrestricted production histories remain open; the three audited ZTF routes supply detection-scoped evidence, and explicit required-component empty-array receipts can establish zero. |
| D3.4–5 extrema ranges and branch-local membership | Done in #360. Facade regressions exercise witnessed bounds, unavailable flags and short bands. |
| D3.6 actual route completeness and delivered bands | ALeRCE/ZTF, Lasair/ZTF and ANTARES/ZTF detection-scoped routes and audited band delivery are implemented under item 7. LSST and measurement completeness remain open. |
| D3.9 scalar/exists/Boolean/taxon compatibility | Done: existing semantics and taxon validator retained, with maintainer-run regression acceptance through #361. |
| Later filter, continuation, non-refill, facade acceptance | Done in #361 with controlled native payloads, selected downstream IDs, immutable continuation, failure propagation and non-refilling latest. |
| Initial where/latest and missing-material placements | Explicit guards done in #361; expanded scheduling remains item 4a. Initial discovery uses only its discovery call, not supplementary evidence. |
| Collection confirm | Explicit rejection done in #361, including attached propositions; bare existence confirm after a filter remains independent. Collection voting is out of scope. |
| Measurement acquisition, named binders, FP policy | Measurement acquisition and broker-held FP component requests are implemented under item 7. Named binders remain item 10; on-demand FP services remain item 11. |
| Provider mappings, route metadata, endpoints, policy, transports | Not applicable to this slice; no YAML or physical-contract changes. |

With admitted material and open completeness, witnesses can prove
lower bounds (`count >= N`), a bright minimum (`min < x`) and `any`. Exact counts,
zero-count claims, `min > x`, and an `every` failure based only on a short band stay
unknown until applicable collection completeness exists. An explicit empty-array
receipt for a required component can prove its zero count; it does not prove band
delivery or close a nonempty history. The audited ZTF detection subsets are
the scoped exceptions described above. A contradictory known
witness can still disprove a comparison. Local evaluation does not bypass the
public DSL or canonical planner material/placement guards.
