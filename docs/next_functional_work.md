# Next functional work: classification and collection predicates

User priorities after the discovery integration and architectural cleanup:

1. Coarse classification normalization.
2. Universal `best` under an explicit scientific policy.
3. Elegant, extensible collection-level DSL reasoning.

These are desired functionality, not optional extras inferred from a narrower
beta definition. Deployment remains deploy-yourself, with future NLP potentially
using the project LLM server. A hosted session/database/service redesign is not
part of this sequence. Root `ARCHITECTURE.md` owns architectural boundaries.

## Classification contract to settle

Use real same-object assertions to specify eligible outputs, versions, coarse
label mappings and method-specific acceptance. A low-ranked assessment being
listed does not itself support that class. Define universal `best` as a derived,
named/versioned result with its input evidence and alternatives retained. Do not
pick the largest heterogeneous score or overwrite upstream preferred outputs.

Scientific acceptance rules and precedence have not yet been chosen. Write a
concrete input/output table before implementing them; do not manufacture defaults.
Confirmation must retain the contributing broker's own evidence and vote once
per broker, even when several outputs or shared methods support a proposition.

## Collection reasoning requested by the user

The user supplied these illustrative forms (the first uses an old noun):

```text
where/filter count(
  detection@ztf:fink where quality.real_bogus > 0.9
) >= 5

where count(lightcurve.points where measurement.valid = true) >= X
and every band in ["u", "g", "r", "i", "z", "y"] satisfies
    count(lightcurve.points where band = $band
          and measurement.valid = true) >= 5
```

`where/filter` above means either placement, not a slash operator. Preserve these
as user examples; the current canonical noun is `measurement`. The examples are
not a claim that this syntax or `measurement.valid` is currently implemented.

Design the smallest reusable expression/collection model that handles these and
unseen cases. Do not add five scientific-cut-specific keywords or another query
engine. Settle, with examples:

- Candidate-local scope versus cross-candidate aggregation.
- Counts of semantic records versus intrinsic lightcurve points; avoid counting
  the same provider observation twice through two representations.
- Predicate binding to one collection element and lexical quantified variables.
- Missing/invalid values, empty collections, missing requested bands and vacuous
  truth. Do not treat absent provider evidence as zero or success without a rule.
- Exact provenance and quantity/kind distinctions in the counted population.
- Dependency/material scheduling, initial `where` before latest, later `filter`
  without refill, continuation and serialization.
- Local evaluation as the reference meaning; admit native pushdown only with a
  proof of equivalent population and semantics.

The normal pipeline remains DSL → canonical predicates/IR → existing planning
and normalized evidence evaluation. Future NLP targets the same contract.
