# Discovery integration: semantic audit before main

Date: 30 October 2026.

Remote integration inspected: `6aa9b161c65fb1efb906d74f9a5ae7403a89e87e`
(`integration/discovery-completion`, PR #328). Main inspected:
`7536b2da1e7bcaeb5a2f4030a774c0f1d92bfa77`. Local reporting fix:
`f49619773c09d1c49504cf0382fb4373ff2940ae`; it is not on the remote integration
ref at this audit checkpoint. The comparison with main covers 147 changed files.

Draft [PR #329](https://github.com/sambolino/alertissimo/pull/329) starts the
existing main-target CI workflows. It is a validation baseline, not approval to
merge. The old integration plan and its historical runbooks are preserved.

## Decision

**Hold the main merge.** The temporal/provider/material milestones have substantial
recorded and user-reported live evidence, but the compiler/evaluator still has
predicate-preservation and assertion-evaluation defects. Existing checks do not
cover the counterexamples below. A green baseline cannot establish that the
agreed declarative contract is implemented.

This is a source audit: no project imports, tests, builds, applications or broker
requests were run locally. Findings distinguish direct control-flow deductions
from behavior that still needs an executable regression. No captured data was
changed to manufacture passing results.

These are defects/gaps present on integration, not a claim that all were added
by this series. AST comparison with main shows unchanged candidate-search/lookup
construction, predicate comparison/evaluation, confirmation attachment checks,
quorum evaluation and classification recipe admission. The grammar is identical
to main. Integration's lowering changes add ontology-family expansion while
retaining the predicate-placement branches discussed below.

## The agreed contract

- `with ... where` requests semantic material and constrains candidates. Native
  request filters and local pruning are physical realizations of that intent.
- A later `filter` adds a selection to the current population, especially during
  continuation. It does not exclusively own the local pruning mechanism.
- `confirm` expresses an explicit proposition/existence quorum. It is not a
  universal classifier or a claim of statistical independence.
- Initial predicates must be satisfied before global latest selection. A later
  continuation filter does not refill a previously selected latest-N population.
- Missing classification evidence is not a positive non-SN assertion. A class
  and its probability must be attributable to the same assertion.
- Mapping/retrieval/comparison precede additional endpoint searches by class.

## Findings

### A1 — Fresh lookup predicates can disappear (merge blocker)

Example of the affected shape, using already accepted single-broker syntax:

```text
objects ZTF21abfmbix from ztf via fink
with classification via fink where best.class = "SN candidate"
```

`dsl/lowering.py::_candidate_operation` returns a `LookupStep` and an empty
consumed set. It does not process predicates. In `_lower_surface_intent`, a
requirement emits its Get, but its predicate only emits a `FilterStep` when its
index is at or after the first explicit `filter`. With no explicit filter, that
condition never holds. A general `WhereClause` on a lookup also reaches the final
skip branch. Ontology/capability checks do not add the missing condition.

Result inferred directly from lowering: lookup plus retrieval, with no scientific
predicate in either Step. By contrast, `_lower_fragment_intent` emits Get plus
Filter for the same scoped condition in a continuation.

Repair: preserve conditions on named populations in existing IR, applying them
after the required material is available. Never require users to insert an
unrelated `filter` as a compiler workaround. Add public validation, compiled-IR,
execution and continuation regressions for matching and rejected candidates.

Also audit lookup clauses such as within/inside/latest: unsupported combinations
must fail clearly rather than fall through the same silent skip path.

### A2 — Accepted clauses after a filter can be silently ignored (merge blocker)

The full-script grammar accepts general `where`, `inside`, `within` and `latest`
clauses at arbitrary clause positions. `_candidate_search` only consumes the
prefix before the first `FilterClause`. The later general clauses are skipped
by `_lower_surface_intent` without an equivalent Step or an explicit error.

A supported shape such as a bounded discovery, an explicit filter, an explicit
classification retrieval and then a general classification `where` can therefore
retain the retrieval while losing the last condition. Fragment grammar already
rejects standalone `where`; full-script behavior must be equally deliberate.

Repair: define which clauses are declarative initial constraints and which add a
later operation; lower every admitted condition or reject the placement before
execution. Do not silently move a continuation condition across a selection.

### A3 — Same-assertion correlation breaks in mixed conjunctions (merge blocker)

`normalization/predicate.py::evaluate_portfolio_predicate` correlates fields when
the entire current predicate subtree has exactly one record selector. When a
flat AND also contains a summary selector, it recursively evaluates each atom
independently. `dsl/expression.py::and_expr` produces that flat n-ary conjunction.

Counterexample to turn into a regression:

- assertion A from one model/version: class SN, probability 0.2;
- assertion B matching the same selector: class AGN, probability 0.99;
- candidate summary: detection count 10.

```text
filter classification@model:broker.best.class = "SN" and classification@model:broker.best.probability >= 0.8 and summary.detection_count >= 5
```

The source control flow accepts the class from A and probability from B. A
parenthesized classification-only subtree rejects it. Adding an unrelated true
summary condition must not change assertion ownership.

The existing `test_residual_classification_conjunction_must_match_one_record`
covers the classification-only subtree, not this mixed-selector case.

Repair the existing predicate evaluation/binding scope. Cover flat/grouped
conjunctions, OR branches, multiple versions, mixed broker selectors, and
pushdown/residual splits. Do not flatten unrelated models into a global best row.

### A4 — Negation can turn absent fields into evidence (merge blocker)

`_compare` returns False for a missing operand or an invalid comparison.
`_evaluate_on_record` then implements NOT with ordinary Boolean negation. If a
matching classification record exists but has no requested class field,
`not (classification.best.class = "SN")` can become True. Ordinary `!=` against a
missing operand already returns False. These expressions therefore have different
missing-evidence behavior. Confirmation uses the same evaluator.

An entirely absent classification record is a separate case: the single-selector
path has no matching records and returns False. The defect must not be described
as every missing-record case voting negatively.

That same single-selector dispatch also mishandles explicit absence questions:
`not exists classification` evaluates False when the family is absent because
the evaluator runs `any(...)` over zero matching records before applying the
NOT. If records exist, their record-existence tests are True, so their negations
are False as well. An explicit absence test therefore cannot be implemented by
the same per-record existential dispatch as a positive class comparison. This
evaluation-scope issue is separate from the coverage needed to claim that a
queried provider genuinely has no assertion.

Repair: preserve unavailable comparison evidence through negation, so only an
established proposition can count positively. Keep explicit existence/absence
questions distinct. Cover partial records, absent records, null/invalid values,
Boolean combinations and execution-local confirmation votes.

### A5 — Initial conditions are forced onto discovery (unsafe accepted cases and design gap)

`_candidate_search` puts all initial general/scoped predicates into the first
SearchStep. Additional Gets execute later. `pipeline.py` prunes residuals against
each normalized physical execution before accumulating later requested material.
There is no general request-wide dependency scheduling that fetches a different
broker's classification before deciding the original condition.

Concrete unsafe shape, with no temporal/latest admission guard involved:

```text
objects from ztf via alerce
inside (124.87996115142856, -6.0205001, 5arcsec)
with classification via fink where best.class = "SN candidate"
```

The scoped condition carries channel `fink`. The ALeRCE cone call cannot push it
down, so the planner retains a residual. Its normalized ALeRCE response has no
Fink classification record, so the early prune can empty the candidate set before
the Fink Get is bound. A public replay must prove that qualifying candidates are
not returned as an apparently successful empty population. Until correct staged
realization exists, admission must explicitly reject an unproven evidence
dependency rather than execute the wrong selection. This safety requirement is
a merge blocker; the full scheduling extension is planned separately.

One explicit guard in `orchestration/validation.py::_search_recipe_evidence`
even recommends a later filter when a temporal cone's discovery call lacks the
predicate material. This is a current implementation limit, not the desired
public semantic distinction. Some combinations reject early; others can lose
candidates when a residual is evaluated before its evidence exists.

Repair within existing lowering/planning/staging: prove a safe discovery
population, arrange required Gets, evaluate the original predicate on the
appropriate accumulated material, then apply global latest. Do not append a
filter after an already reduced latest-N search and claim equivalence. Retain
explicit failures for unavailable/unbounded/incomplete discovery contracts.

### A6 — Multi-broker requirements are not implemented (design gap)

`dsl/grammar.lark` uses a single NAME for `via_clause`; only `confirm` uses a
broker list. `RequirementClause.via`, candidate context and lowering also hold
one broker. `with classification via alerce, fink` does not currently parse.
Two explicit requirement lines are not evidence that the requested list syntax
already works. Adding the grammar alone would not fix A5.

Repair: preserve broker lists through the existing surface, capability checks,
lowering and IR sources. Preserve single-broker compatibility, exact scope,
deduplication and continuation. Material providers are not automatically a demand
that every candidate exists at every provider, nor a voting quorum.

### A7 — Confirmation meaning depends on adjacency (design gap)

`_lower_surface_intent` and
`capability_validation.py::_adjacent_confirm_predicate` attach only the immediately
preceding top-level `WhereClause`. A scoped `with ... where` does not attach.
An intervening `with` or `latest` changes the Confirm into bare existence quorum.
This behavior is explicitly expected by `tests/test_dsl_confirm.py`.

Continuation accepts `confirm` but not a standalone `where`, and
`_lower_fragment_intent` emits a predicate-free Confirm. Thus scoped conditions
followed by confirmation cannot currently express the same proposition quorum
across fresh and continuation forms.

Keep the existing useful mechanics: exact object identity, execution-local
evidence, distinct-broker counting, and provenance. Define proposition binding
explicitly in the existing surface/IR; reject ambiguous attachment instead of
silently changing the question. Do not introduce a separate consensus operation.

### A8 — Classification retrieval remains uneven (declared capability gaps)

- ALeRCE ZTF/LSST: fresh `query_probabilities`, local producer selection,
  model/version/class/probability/rank evidence. It need not populate `best.*`.
- Fink ZTF: alert-associated label and named assessments from `objects`.
- Fink LSST: useful object labels and source assessments are mapped, but generic
  fresh retrieval has two feasible recipes. Selecting producer `fink` alone does
  not distinguish object-level and source-level material.
- Lasair: object and Sherlock routes can compete. Explicit Sherlock/TNS intent
  and singular/plural targets change compatible choices. Do not advertise every
  generic retrieval as unambiguous.
- ANTARES ZTF/LSST: no classification mappings or GetClassification recipe.
  Catalogue associations are not automatically physical transient classes.

The first two ambiguity cases are deliberately covered in
`test_real_classification_alternatives_remain_ambiguous`. Preserve the ambiguity
guard; make the requested evidence and recipe contract sufficient to resolve it.
Do not pick the first YAML alternative. The current classification resolver
admits one-call recipes only, so collecting both Fink LSST views also needs an
explicit extension in that existing resolver.

### A9 — Coverage and status documentation need final reconciliation

The latest paired shared checkpoint is on `4d93b51`, before the application and
acceptance additions. Three checks have now been requested on `6aa9b16` through
draft PR #329; their links/status must be read from GitHub, not inferred from
the earlier green checkpoint.

Static expansion of the three pytest commands covers 133 of 144 top-level test
modules. Eleven modules are absent, including changed
`test_antares_lsst_authoritative_payloads.py`, `test_intrinsic_array_collector.py`,
`test_photometry_mapping_migration.py` and `test_portfolio_browser.py`. Three green
checks are not the requested full offline sweep. Packaging is covered by the DSL
workflow's installed-wheel step. This audit has not run the missing tests.

Baseline run links on `6aa9b16`:

- [DSL compiler and installed wheel](https://github.com/sambolino/alertissimo/actions/runs/41121673004).
- [Semantic registry](https://github.com/sambolino/alertissimo/actions/runs/41121672856).
- [Streamlit UI](https://github.com/sambolino/alertissimo/actions/runs/41121672949).

All three baseline workflows completed successfully on `6aa9b16`:

| Workflow | Result |
| --- | --- |
| DSL compiler | 1,447 passed in 876.75 seconds; installed-wheel check PASS, 36 runtime resources, eight cone recipes and enrichment expansion/planning |
| Semantic registry | 1,003 passed / one skipped; all eight provider mapping validations passed |
| Streamlit UI | 82 passed |

The optional pandas-based projection test is skipped in the focused registry
environment; it is included in the UI environment. These counts overlap across
suites and must not be added as a unique-test total. They validate the remote
baseline, not the local reporting fix, the new design, or the uncovered audit
counterexamples. Main remains blocked despite the green baseline.

The native ANTARES reporting fix is local only at this checkpoint. The original
live guide/progress entries also predate the user's later successful historical
cases. Those later results are recorded below without rewriting earlier events.

## What the old plan has accomplished

The revised saved plan and repository continuation were both reviewed. Original
ALeRCE classification bugs are fixed on main (#293). The integration contains
the remaining Fink window alignment; shared and Lasair latest admission; scoped
ANTARES search/default/first/last/latest; required-material inventory, cutouts
and units; measurement/enrichment ontology revision; per-candidate access; and
recorded/live acceptance runners.

Fink latest/first/last and remaining Rubin temporal/latest routes have concrete
documented admission limits, not universal activation. The end-topic consultation
has now happened: prioritize mapped retrieval and deliberate comparison; defer
additional classification endpoint search until last. The
[new design/PR plan](classification_evidence_design_plan.md) records that decision.

## User-reported live evidence

These are console outcomes supplied by Veljko; the local `/tmp` artifacts are on
his machine and were not independently opened during this audit.

| Run / case | Outcome and exact scope |
| --- | --- |
| First/repeated default sweeps | ALeRCE unconstrained/named classification; Fink original seven-day class/time; two-object consumer; Fink cutouts PASS |
| Historical filter | Fink discovery/filter/retrieve with `--window-hours 168`: PASS |
| ALeRCE default | RA 313.7733232785203, Dec 39.09800386874637; 2018-06-17 to 2018-06-18 UTC: PASS |
| Lasair default | RA 124.8799444, Dec -6.0205159; 2020-11-12 to 2020-11-13 UTC: PASS |
| ANTARES default | RA 50.84810593071894, Dec 37.46783501531417; half-width 0.1 arcsec; 2026-07-02 to 2026-07-03 UTC: PASS |
| ALeRCE first / last | 2018-06-17 to 18 / 2025-12-23 to 24 UTC: both PASS |
| Lasair first / last | 2020-11-12 to 13 / 2020-12-11 to 12 UTC: both PASS |
| ANTARES first / last | 2020-01-19 to 20 / 2026-07-02 to 03 UTC: both attempts returned server 500; live first/last acceptance remains unverified |
| ANTARES direct lightcurve control | ZTF20aafqubg: PASS, 316 points, 70 detections, 246 limits |

Evidence roots: `/tmp/alertissimo-rerun.uvYACA`,
`/tmp/alertissimo-historical.1WafOU`, `/tmp/alertissimo-extrema.PAEmro`.
All eight runner scenario types have a nonempty PASS across separate runs and
different windows/fields; this is not one all-default all-PASS sweep. Default
ANTARES also returned a 500 on an earlier attempt, so failures are not isolated
to first/last. Their local reductions do not add time parameters to ANTARES's
coordinate search; the latest failed call sites need their own error logs.

## Required next actions

1. Repair A1/A2 predicate loss, A3/A4 assertion/missing-evidence correctness, and
   A5's premature evaluation of unavailable requested material in
   small branches on integration, with regressions exercising actual public
   execution and confirmation as well as lowering.
2. Decide/implement the concrete A5-A7 declarative scheduling/scope behavior from
   the new plan; do not present it as completed by the old provider milestones.
3. Include the pending reporting fix and update status documents. Preserve
   first/last operational uncertainty; do not claim general ANTARES outage.
4. Cover the four changed test modules missed by focused CI and run the full
   offline sweep with appropriate dependencies. Keep the installed-wheel check.
5. Remove the three temporary integration CI exclusions only at final closeout,
   check the final main base/head, and require successful current-head checks.
6. Mark PR #329 ready and merge only after the blockers have actually been
   repaired and validated. Neither this audit nor a green baseline authorizes
   replacing scientific behavior with documentation caveats.
