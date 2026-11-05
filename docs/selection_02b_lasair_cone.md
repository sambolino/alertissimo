# Lasair cone latest with required summary coverage

Branch `feat/selection-02b-lasair-cone`, based on integration `1680d38` / PR #313.
Target `integration/discovery-completion` and squash after focused local checks.

```text
objects from ztf via lasair
inside (120, -6, 5arcsec)
within 10d
latest 2
with lightcurve via lasair
```

Cone latest now admits unwindowed, default within, first within and last within
populations. The complete cone identities are followed by a required projected
object-summary query. Temporal membership, when requested, precedes global
ranking by overall summary last detection. Measurements remain intact.

## Proof through the existing architecture

The existing recipe format gains `latest_selection: {call: 1, complete: true}`
for finite discovery whose ranking material comes from a later required call.
The compiler requires uncapped array discovery, a required identity-dependent
summary array, a constant identity/recency projection, and an identity batch
bounded by the explicit summary limit with offset zero. The provider's audited
complete population remains an authored contract, not an inference from row
count or a successful HTTP response.

The compiled proof carries raw field names from existing mappings into the
existing EndpointPlan model. Staged and offline normalization check that the
summary execution group covers exactly the discovery identities, once each,
with finite numeric recency. Missing, duplicate or foreign identities; malformed
collections; absent/invalid dates; and required-call failures cannot become a
successful top-N result. Coverage is checked across all identity batches without
decoding SQL conditions. Empty cone discovery remains a valid empty result.

All cone calls used for latest explicitly request `all`. The ordinary unwindowed
cone retains its original optional-summary recipe. A separate latest-only recipe
makes that summary required; temporal recipes already require it. Selection-aware
admission avoids creating a second feasible recipe for ordinary cone searches.
The existing conservative latest reuse policy fetches downstream lightcurves for
selected IDs. Continuation replays the original calls and temporal reference.

There is no new architecture layer, scientific Step, user keyword, or dependency.
The changes stay within provider recipes, compiled evidence, planner models and
the existing normalization checks. A new metadata proof is necessary because the
cone response itself has no recency and an optional supplement cannot establish
the ranking population.

Initial predicates on cone latest remain deferred: discovery contains thin IDs,
so conditions cannot be checked against summaries before enrichment. Use the
existing SQL semantic discovery for numeric initial conditions. A later Filter
is an explicit operation over the already-selected population. Classification
joins and additional Rubin discovery remain reserved for the agreed discussion.

## Source audit

The previously pinned Lasair
[`2b940d41c456545164c587e0f053e6312c2d105a`](https://github.com/lsst-uk/lasair4/tree/2b940d41c456545164c587e0f053e6312c2d105a)
serializer calls `coneSearchHTM` on `objects` and returns every resulting ID in
`all` mode. The helper's inspected implementation at
[`gkutils 2e7aeb9d041a1860a83b054dc5cf9d9567fda0ba`](https://github.com/genghisken/gkutils/blob/2e7aeb9d041a1860a83b054dc5cf9d9567fda0ba/gkutils/commonutils/generalutils.py)
uses an uncapped HTM superset query and then exact angular separation. `QUICK`
selects fewer columns; it is not a row limit. The existing bounded primary-key
summary query uses batches of at most 100 IDs with limit 100 and offset zero.

This describes the broker's reported catalogue, not an atomic snapshot. The
upstream helper can also return an empty list with an error message on database
failure, and the serializer does not forward that message. A client cannot
distinguish that hidden failure from genuine empty discovery. This branch
detects observable response defects and summary coverage failures; it does not
repair that upstream error-reporting behavior or claim to identify it.

## Local handoff

No tests, project imports, builds, apps or live provider requests ran here.
Python AST, YAML syntax, whitespace and Git bundle checks are the available
static verification.

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_lasair_time.py \
  tests/test_dsl_live_material_lineage_matrix.py \
  tests/test_orchestration_composite_cone_recipes.py \
  tests/test_orchestration_selection_recipes.py \
  tests/test_orchestration_predicate_recipes.py \
  tests/test_orchestration_normalization_reuse.py \
  tests/test_api_continuation.py \
  tests/test_recipe_registry.py \
  2>&1 | tee /tmp/alertissimo-selection-02b-tests.log
```

Cases cover all four temporal forms, ordinary recipe admission, exact summary
coverage, a 101-object/two-summary-batch population, full membership before
latest, selected-ID continuation, offline replay, and malformed completeness,
projection, requiredness and batch-limit declarations. Existing fixture scopes
exclude latest-only alternatives when testing the old optional supplement.

Keep the agreed local checks / small squash PR workflow. Because this branch adds
serialized planning evidence and a normalization check, run one intermediate DSL
checkpoint after its integration merge:

```bash
gh workflow run dsl.yml --ref integration/discovery-completion
gh run list --workflow dsl.yml --branch integration/discovery-completion --event workflow_dispatch --limit 3
```

Full CI remains required on the final integration PR. Next: Fink latest admission.
