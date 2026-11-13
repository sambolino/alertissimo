# Collection expression contract

Agreed design with D3 decisions fixed on 13 November 2026; **syntax is not yet
implemented or runnable**. The first implementation slice retains ontology array
and parameter metadata and versions WorkflowIR. It does not admit these expressions.
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

These are the agreed evaluator/admission contract, not a claim that evaluation is
implemented in the structural-metadata slice.

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
   bands never redefine the origin's domain or prove completeness.
7. **Bind one product.** An aggregate/quantifier collection selector binds one
   product record per candidate, without pooling or first-match selection.
   Statically visible ambiguity requires an existing qualifier, for example
   `lightcurve@ztf:fink.points`. Multiple matching runtime records produce unknown
   and a visible `ambiguous_product` diagnostic, not an exception. Never combine
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
    defaults to integer `dsl_version: 2`; serialized IR missing the field loads
    as pre-collection version 1, including within a WorkflowRun. A runtime refuses
    a newer version. Scalar continuation preserves the existing version. Version
    2 metadata alone does not assert that collection syntax is runnable.

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

Initial collection `where` combined with `latest`, or another placement lacking
guaranteed material before evaluation, must explicitly report deferred **item 4a**.
Collection predicates within `confirm` are out of scope. A later `filter` after
retrieval is the minimum required end-to-end placement for a subsequent slice.

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

Flag mappings are currently uneven; see item 7. Current grammar is
[`expression.lark`](../alertissimo/dsl/expression.lark); repetition/domain metadata
must be retained by the existing semantic-model owner.

## Deferred extension

Named binders such as `as p` are reserved for later reevaluation of self-joins and
correlated nested collections (item 10). They must not replace the simple forms
above. FP request syntax/policy is separately deferred in item 11.
