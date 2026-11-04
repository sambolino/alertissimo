# C4b — Latest after initial classification evidence

Branch: `fix/dsl-latest-after-classification`.
Base: `a54aab3` on `integration/discovery-completion`, after merged C4a and its
reported successful CI checkpoint. Keep main-target #329 draft.

## Scientific behavior

```text
objects from ztf via alerce
inside (124.88, -6.02, 5arcsec)
latest 2
with classification via fink
where classification@fink:fink.best.class = "SN candidate"
```

Discover the spatial population completely under the existing latest contract,
retrieve its Fink classification, evaluate the whole initial condition, then
choose the two most recent surviving objects. A newer nonmatching object cannot
consume a selection slot. Duplicate discovery rows do not add candidates.
Equal recencies use the established ascending (origin, object_id) tie break.
All material for surviving objects remains available; selection does not reduce
their observations. Inline scoped where and general qualified where retain C4a's
equivalent lifecycle behavior.

Rank by the original discovery's recency evidence. A Fink response can contain
newer dates than the ALeRCE discovery; those dates do not change the requested
discovery ranking. Existing required summary/history proofs remain attached to
the discovery, with their coverage and pagination checks intact. This branch
does not declare a new provider's completeness or recency capability.

An explicit later filter consumes the already selected objects. If it removes
all of them, do not refill from other initially matching candidates. Continuation
replays the same physical prefix and selection, does not mutate old snapshots,
and targets only surviving IDs for newly appended retrievals.

## Representation and execution

The operations remain ConeSearchStep → existing Gets → FilterStep. There is no
new Step, service, recipe format, provider mapping or architecture layer.

`SearchSelection` gains one optional canonical field, `after_step`. None retains
the existing immediate discovery selection. An integer identifies the initial
evidence Filter after which the owning discovery's selection must apply. The
compiler writes the actual emitted occurrence index, before any explicit later
filter. The field survives WorkflowIR and WorkflowRun JSON round trips.

The existing WorkflowRun alignment validator rejects absent/backward references,
non-Filter boundaries, and intervening operations other than targetless Gets.
It runs before endpoint planning/execution. Temporary compiler IR prefixes stay
usable for existing material admission proofs.

The staged runtime and offline final normalization use the same deferred selector.
They intersect current survivors with the discovery snapshot, obtain ranking
values only from that snapshot, and retain the current enriched Portfolios.
Discovery and retrieval snapshots remain complete and immutable; the initial
Filter snapshot owns the latest-selected population. Existing native latest
without a deferred boundary retains its behavior.

Existing contract admission still requires mapped identity and recency, exhaustive
pagination or required finite-population evidence, compatible projections, and
no top-N evidence truncation. Missing recency for a surviving object, a required
request failure, or pagination-policy exhaustion cannot yield a successful
partial latest result. Mapped-but-absent classification follows the existing
unknown predicate policy and cannot create a match.

## Scope remaining after this branch

- C4a's temporal, mixed-owner/multi-channel, unbounded and initial Confirm/Match
  guards remain in place. This branch only adds latest to the C4a population.
- Provider pairs without an existing discovery latest contract remain deferred,
  including Fink ZTF cone and ALeRCE LSST. No Rubin latest contract is invented.
- C4 is not complete. Temporal composition and broader dependency scheduling
  require subsequent small branches; Confirm scope is C5.

## Verification and handoff

Preparation uses source review, AST/YAML parsing, whitespace/path checks and Git
bundle verification. No project imports, tests, builds, app runs or broker calls
were performed in the preparation environment.

`tests/test_dsl_latest_evidence.py` uses synthetic transports through the production
registry executor. It covers three discovery pages, duplicate identity rows,
newest-candidate rejection before selection, frozen recency despite contradictory
enrichment dates, ties, full measurements, immutable continuation and no refill,
downstream/vacuous IDs, empty/missing classification, missing recency, request and
pagination failures, unsupported contracts, serialization and invalid boundaries.
The Lasair composite replay additionally checks that required summary coverage
is still established before external classification is fetched.
It is included in DSL CI's existing wildcard and explicitly in registry CI.
The prior C4a latest-deferral test is replaced by the positive latest coverage;
its temporal guard remains asserted.

Run locally:

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_dsl_latest_evidence.py \
  tests/test_dsl_predicate_preservation.py \
  tests/test_dsl_capability_validation.py \
  tests/test_dsl_lowering.py \
  tests/test_dsl_fragments.py \
  tests/test_dsl_public_api_serialization.py \
  tests/test_orchestration_ir_models.py \
  tests/test_orchestration_runtime.py \
  tests/test_orchestration_selection_recipes.py \
  tests/test_orchestration_normalization.py \
  tests/test_orchestration_lasair_time.py \
  tests/test_orchestration_time_membership.py \
  tests/test_api_continuation.py \
  2>&1 | tee /tmp/alertissimo-latest-after-classification-tests.log
```

After green local tests, push, PR and squash into integration. This modifies
selection and its execution lifecycle, so it needs a manual DSL/registry checkpoint
on the merged integration SHA before proceeding to broader C4 combinations:

```bash
gh workflow run dsl.yml --ref integration/discovery-completion
gh workflow run semantic-registry.yml --ref integration/discovery-completion
```

No new live provider acceptance is needed for this lifecycle change. Final
main-target CI remains required on its eventual head; keep #329 draft.
