# Collection expression contract

Agreed design with D3 decisions fixed on 13 November 2026. **Syntax and canonical
IR are implemented; local evaluation is prepared, but collection expressions remain
not runnable through workflows.** The evaluator in the existing normalization
owner adds ranges, Kleene quantifiers, branch membership and ambiguity warnings.
Admission remains gated for the next slice. Evaluation acceptance awaits the
maintainer's local tests and CI; static source checks are not execution evidence.
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

These are the agreed evaluator/admission contract. Syntax/IR represents and
validates the constructs. The existing normalization predicate evaluator now
implements their local evaluation; workflow admission remains a separate slice.

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
   bands never redefine the origin's domain or prove completeness. Delivery
   declarations and their loader amendment are deferred to the first per-route
   collection-completeness slice under item 7. Recipes and capability files remain
   untouched in the syntax, evaluation and admission slices.
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

For testing the closed-bound branch, the evaluator accepts transient explicit
evidence keyed by `(internal_record_id, exact_array_path)`, with completeness and
delivered-band values. Synthetic test proofs exercise this branch; no production
route supplies them. The evidence is not stored in Portfolio, WorkflowRun or IR.
No current response, summary count, temporal proof or observed band implicitly
closes a collection. Actual route evidence and declarations await item 7.

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

## Instruction accounting at the evaluation checkpoint

| Requirement | Status / owner of remaining work |
|---|---|
| Ordered arrays/items, parameter scopes, declared filters | Done in the structural foundation; scalar-field recognition extended here. |
| D3.10 versioning and JSON representation | Done in foundation and syntax/IR; existing version semantics unchanged here. |
| Count/min/max/quantifier syntax and canonical nodes | Done in syntax/IR; workflow execution remains gated. |
| Parenthesized multiline, comments, source coordinates | Done in syntax/IR; grammar unchanged here. |
| D3.3 static empty restrictions, domain members and shadowing | Static checks done in syntax/IR; empty runtime domains remain unknown, including under NOT, in evaluation. |
| D3.7–8 product/output qualification and runtime ambiguity | Static checks done in syntax/IR. Runtime ambiguity, output-local witnesses and existing warning-channel propagation prepared here. |
| Reference/material/headline walkers; no native pushdown | Done in syntax/IR. Material selection now controls collection audit projection without fragment re-evaluation. |
| D3.1–2 count ranges, quantifiers, exact NOT duality | Prepared here with synthetic open/complete-evidence regressions; local acceptance pending. |
| D3.4–5 extrema ranges and branch-local membership | Prepared here, including missing leaves, other-band exclusion and explicit limit/quality conditions; local acceptance pending. |
| D3.6 actual route completeness and delivered bands | Deferred to item 7's first collection-completeness slice; no route claim here. |
| D3.9 scalar/exists/Boolean/taxon compatibility | Existing semantics and taxon validator retained; scalar and collection regressions run locally by the maintainer. |
| Later filter, continuation, non-refill, facade acceptance | Deferred to admission slice; all collection workflow execution is gated here. Internal filter/warning propagation is prepared, not facade acceptance. |
| Initial where/latest and missing-material placements | Explicit item-4a rejection belongs to admission slice. |
| Collection confirm | Rejection belongs to admission slice; execution unavailable here. |
| Measurement acquisition, named binders, FP policy | Deferred to items 7b, 10 and 11 respectively. |
| Provider mappings, route metadata, endpoints, policy, transports | Not applicable to this slice; no YAML or physical-contract changes. |

Once admission lands with open completeness, witnesses can prove
lower bounds (`count >= N`), a bright minimum (`min < x`) and `any`. Exact counts,
zero-count claims, `min > x`, and an `every` failure based only on a short band stay
unknown until applicable collection completeness exists. A contradictory known
witness can still disprove a comparison. Local evaluation does not bypass the
public DSL or canonical planner admission gate at this checkpoint.
