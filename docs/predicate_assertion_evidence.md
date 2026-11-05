# R2 — Assertion ownership and unavailable predicate evidence

Branch: `fix/predicate-assertion-evidence`.
Base: `ba59032`, the integration squash of R1 (#330).
Target: `integration/discovery-completion`. Keep main-target #329 draft.

This implements the A3/A4 repairs from the
[semantic audit](discovery_semantic_audit.md) within the existing predicate
evaluator and pushdown realization. No new IR nodes, architecture layers,
provider mappings, DSL keywords, retrieval routes or comparison UI are added.

## Candidate selection

Each exact `(semantic noun, producer, channel)` selector binds one record for the
whole Boolean expression. A class, probability, version and other conditions
using that selector must be satisfied by one assertion. Adding a summary
condition or moving parentheses around an AND does not permit mixing records.
Different explicitly qualified selectors can have independent witnesses.
Unqualified references remain broad; qualify both class and score to compare a
particular producer/channel. R2 does not infer aliases between differently
qualified selectors or choose a preferred model/version.

For example, an SN assertion with score 0.2 and an AGN assertion with score 0.99
cannot satisfy SN with score >= 0.8, even with an unrelated true summary clause.
OR alternatives remain alternatives; a missing family in one alternative does
not prevent an established match in another. Matching keeps the whole candidate
Portfolio, including its other assertions and measurements.

If native filtering pushes one condition but a condition on the same selector
remains local, the residual retains the original predicate. Server selection of
an object does not identify which returned assertion must supply the local
score. The existing discovery-material guard applies to the expanded residual:
missing projected evidence defers planning rather than inventing a witness.
Unrelated selectors retain their existing partial-pushdown behavior; fully
translated native predicates and SQL/Elasticsearch rechecks remain unchanged.

## Missing values, negation and explicit absence

Comparisons can be true, false or unknown internally. Missing fields/records,
null, nonfinite numeric values, incompatible scalar types and nonscalar operands
are unknown. Numeric strings are not coerced, and booleans are not numeric
scores. Only established True selects a candidate or supplies a proposition vote.
NOT preserves unknown, AND with a known false condition is false, and OR with a
known true condition is true. Established AGN can satisfy class != SN; an absent
class cannot.

Positive existence participates in the same-record witness. Explicit NOT EXISTS
checks all matching records in the current material view: a partial record cannot
prove absence when another matching record supplies the field. Null/nonfinite
field values do not establish field existence; a record itself can still exist.
Negation through grouped Boolean expressions uses the same absence rule.

NOT EXISTS describes this materialized view. It does not establish that an
unqueried provider has no assertion, guarantee coverage or turn a failed request
into an empty response. Ordinary NOT-comparison predicates continue to ask for
an established contradictory assertion; they do not mean that no other record
satisfies the positive comparison.

Confirm continues to use its own execution-local Portfolios, exact candidate
identity and at most one vote per broker. It benefits from the repaired evaluator;
R2 does not change proposition attachment or bare existence quorum. Those scope
rules remain C5 work.

## Verification and handoff

Preparation used source review, static Python AST parsing, whitespace and bundle
verification only. No project imports, tests, builds, applications or broker
requests were run here. Passing status must come from the local run below.

The new `test_orchestration_predicate_evidence.py` is already included by the
existing DSL workflow's `tests/test_orchestration_*.py` glob. Its synthetic
fixtures cover mixed/grouped/OR predicates, versions and channels, missing and
invalid evidence, explicit absence, field comparisons, partial native filtering,
execution-local confirmation, and public fresh/continuation selection with
survivor measurements preserved. No captured payloads are changed.

Run locally after importing the bundle and rebasing onto integration:

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_predicate_evidence.py \
  tests/test_dsl_predicate_realization.py \
  tests/test_dsl_predicate_preservation.py \
  tests/test_orchestration_predicate_recipes.py \
  tests/test_orchestration_required_predicate_bindings.py \
  tests/test_orchestration_confirmation.py \
  tests/test_orchestration_confirmation_recipes.py \
  tests/test_orchestration_confirm_downstream.py \
  tests/test_dsl_confirm.py \
  tests/test_api_continuation.py \
  tests/test_orchestration_normalization_reuse.py \
  tests/test_alerce_semantic_search.py \
  tests/test_fink_semantic_search.py \
  tests/test_lasair_semantic_search.py \
  tests/test_antares_semantic_search.py \
  2>&1 | tee /tmp/alertissimo-predicate-assertion-evidence-tests.log
```

After local success, push and squash the small PR into integration. Then run one
intermediate DSL/registry CI checkpoint on the resulting integration SHA because
this repair changes the evaluator shared by discovery, Filter and Confirm:

```bash
integration_branch=integration/discovery-completion
git switch "$integration_branch"
git pull --ff-only origin "$integration_branch"
git rev-parse HEAD
gh workflow run dsl.yml --ref "$integration_branch"
gh workflow run semantic-registry.yml --ref "$integration_branch"
gh run list --workflow dsl.yml --branch "$integration_branch" --event workflow_dispatch --limit 3
gh run list --workflow semantic-registry.yml --branch "$integration_branch" --event workflow_dispatch --limit 3
```

Inspect/watch the returned run IDs and verify their head SHA matches this squash.
Do not use old baseline CI or skipped draft jobs as validation. No live provider
rerun is required for this evaluator repair. #329 stays draft and main stays
unchanged pending release review; a checkpoint is not permission to merge main.

Next: C1 multi-broker classification requirements, followed by the existing
retrieval/mapping/comparison sequence. Endpoint classification discovery remains
last; C4 scheduling and C5 proposition scope remain explicit outstanding work.
