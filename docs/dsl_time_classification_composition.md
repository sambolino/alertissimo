# C4c — Temporal membership before external classification and latest

Branch: `fix/dsl-time-classification-composition`.
Base: `9f3649a` on `integration/discovery-completion`, after merged C4b (#338).
Keep main-target #329 draft.

## Supported composition

```text
objects from ztf via alerce
inside (124.88, -6.02, 5arcsec)
within 10d
latest 2
with classification via fink
where classification@fink:fink.best.class = "SN candidate"
```

The same initial condition can be scoped inline on the classification requirement.
`latest` is optional. `first within` and `last within` use their existing meanings.

1. Establish the declared spatial population and temporal membership using the
   discovery source's existing contract and evidence.
2. Fetch classification for that temporal population at the other broker.
3. Evaluate the complete initial scientific condition.
4. Apply optional latest using C4b's original discovery recency snapshot.
5. Bind later explicit filters and retrievals to the surviving population.

Default within needs at least one ordinary valid detection in the closed interval;
an overlapping summary range, upper limit, forced point or another broker's date
does not establish that witness. First/last keep their complete-source first/last
detection meanings. Relative windows retain the original pinned UTC reference.
Candidate selection retains every returned record of a survivor, including
observations outside the selected interval.

Classification retrieval cannot substitute for temporal evidence. Its later
summary dates do not change the window or latest ranking. Continuation replays
the same temporal evidence and clock, never reopens the old window against a
new current time, and never refills the earlier latest population after a later
explicit filter.

## Existing architecture and admission

The production change removes the compiler helper's blanket rejection of an
external classification condition when the cone has time_context. The helper
already moves that whole condition onto an existing initial Filter; it leaves
time_context on the discovery Step. C4b's optional after_step selection boundary
continues to point at that Filter. No new IR field or Step is added here.

Existing capability checks must admit the cone's temporal recipe, required
payload/mapping/completeness evidence, exact mode and input translations. Latest
additionally requires its existing recency and exhaustive population proof.
Classification retrieval must map all predicate fields. Existing staging already
applies time selection before target-bound Gets and delays latest until after
the initial Filter. The planner, binder, execution, normalization, incremental
clock handling, provider contracts and mappings are unchanged.

Positive replay coverage uses the ALeRCE/ZTF and Lasair/ZTF temporal contracts.
No provider pair is newly declared temporally complete. Fink/ZTF cone time,
ALeRCE/LSST time and Lasair/LSST time retain their existing deferrals. No Rubin
within/latest contract or classification discovery route is invented.

Remaining C4 guards: mixed discovery/retrieval-owned conditions, several broker
channels, unbounded discovery and initial Confirm/Match. Conflicting named-model
requirements retain C4a's guard. C4 and C5-C7 are not complete.

## Local verification

Preparation performs source review, AST/YAML parsing, whitespace/path and bundle
checks only. No project imports, tests, builds, app runs or broker calls execute
in the preparation environment.

The new public replay module exercises production registry execution, native
ALeRCE page traversal, Lasair required summary/history calls and local selection:

- All three time modes, with and without latest, at both tested source pairs.
- A candidate whose summary overlaps but whose ordinary history has a gap;
  in-window upper limits/forced points cannot rescue it.
- Closed interval boundaries, full retained histories and external dates that
  would reverse latest order if enrichment were incorrectly used for recency.
- Scoped and general where, absolute date intervals independent of a later clock,
  unchanged IR serialization and offline replay, and unmapped classifier rejection.
- Continuation after a 20-day reference-clock change, no repeated old physical
  calls, survivor-only downstream IDs and no refill after later filtering.
- Initial history reuse without temporal candidate resurrection.
- Missing/failed history, failed classification, incomplete required summary
  coverage and pagination-policy exhaustion; unproven contracts stop before IO.

The old blanket temporal-deferral test now guards an unproven LSST contract;
positive temporal composition has the richer replay coverage above. The new
module is in DSL CI's wildcard and explicitly in registry CI.

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_dsl_temporal_evidence.py \
  tests/test_dsl_predicate_preservation.py \
  tests/test_dsl_latest_evidence.py \
  tests/test_dsl_within_modes.py \
  tests/test_orchestration_alerce_time.py \
  tests/test_orchestration_lasair_time.py \
  tests/test_orchestration_time_membership.py \
  tests/test_orchestration_normalization_reuse.py \
  tests/test_api_continuation.py \
  2>&1 | tee /tmp/alertissimo-time-classification-tests.log
```

After local success, push, PR and squash into integration. No additional manual
CI checkpoint is requested for this compiler-only composition slice. C4b's
previous checkpoint requirement remains; subsequent broader/core changes and the
final actual integration head need their planned CI. No additional live provider
acceptance is requested here. Keep #329 draft.

## C4d follow-up

C4c merged as `91f350c`. [C4d](dsl_mixed_cone_predicates.md) prepares summary and
external classification references within one complete initial predicate. It
supersedes the mixed-summary guard for its declared single-source scope, with
required call/projection evidence. Other outstanding guards remain as recorded.
