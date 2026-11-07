# Collection expression contract

Agreed design, **not implemented syntax** at main `b7f9905` (7 November 2026).
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

Before implementation, record decisions for unknown per-element membership, exact
count equality, empty quantifier domains, ambiguous products and unresolved domains.
Do not silently choose new conventions or disambiguation syntax.

## Scheduling and compatibility

Required initial predicate material precedes evaluation and global latest. A later
written retrieval cannot justify evaluation against missing material. Later
`filter` retains non-refilling semantics. Preserve continuation, serialization,
occurrence lineage and physical reuse.

Extend existing expression/IR, evaluation, planning and semantic metadata. New
functions/operators may be added, but existing canonical programs retain meaning.
Keep round-trip, unknown/evidence and compatibility examples suitable for NLP
training. The language-version metadata representation remains undecided.

## Acceptance examples

| Evidence | Expected condition result |
|---|---|
| Six declared bands have established counts 5,5,5,5,5,4 | Every-band at-least-five fails. |
| Only g/r happen to arrive | Do not silently narrow the default domain; distinguish known empty and unavailable bands. |
| Explicit [g,r], each with five qualifying points | Other bands are outside this restricted query. |
| Bright limiting magnitude on an upper-limit point | Does not satisfy a predicate explicitly excluding limits. |
| Missing upper-limit flag | Does not automatically satisfy `upper_limit = false`. |
| Duplicate representations of an observation | No implicit observation double-count. |
| Initial collection predicate plus latest | Complete initial condition precedes ranking. |
| Equivalent later filter | Refine existing candidates without refill. |

Flag mappings are currently uneven; see item 7. Current grammar is
[`expression.lark`](../alertissimo/dsl/expression.lark); repetition/domain metadata
must be retained by the existing semantic-model owner.

## Deferred extension

Named binders such as `as p` are reserved for later reevaluation of self-joins and
correlated nested collections (item 10). They must not replace the simple forms
above. FP request syntax/policy is separately deferred in item 11.
