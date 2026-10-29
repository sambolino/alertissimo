# Shared latest admission after complete temporal verification

Branch: `feat/selection-01-latest-admission`, based on integration commit
`4356353` (Time 04, [PR #310](https://github.com/sambolino/alertissimo/pull/310)).
PR base: `integration/discovery-completion`. Squash this small PR there after
focused local checks, then run the intermediate shared DSL/registry CI checkpoint.
Main remains the final integration target.

## Change

The existing runtime already executes complete discovery, applies residual
predicates and temporal membership, consolidates object evidence, and applies
global `latest N`. Admission previously rejected any recipe with more than one
call. That excluded complete ALeRCE ZTF discovery plus required temporal history
even though its individual contracts were already activated and verified.

Shared admission now permits that composite when:

- Discovery has its existing compiled recency-ordering/completeness contract.
- The recipe has a complete temporal proof and its follow-ups consume discovery
  identities under the existing recipe dependency rules.
- Discovery material contains object identity, recency and predicate fields,
  with the requested producer/channel qualifiers. A later call cannot supply
  evidence needed for predicates already applied to discovery.
- An authored projection retains those fields; a possible mapping outside that
  projection is insufficient.
- No explicit discovery page/count replaces exhaustive discovery, and no recipe
  parameter derives a physical evidence limit from `step.selection`.

The existing selector, pipeline order, recipes, normalization, result model and
IR remain unchanged. No new architecture layer, provider-specific planner path,
endpoint declaration, dependency or user keyword is introduced.

## Resulting behavior

These ALeRCE ZTF forms now validate and plan through the public facade:

```text
objects from ztf via alerce
within 10d
latest 2
with classification via alerce
```

```text
objects from ztf via alerce
inside (124.88, -6.02, 5arcsec)
within 10d
latest 2
with lightcurve via alerce
```

`latest` ranks objects using their overall `summary.time.last_mjd`, after
predicate and temporal selection. It does not rank only the measurements inside
the window, restrict discovery to one page, stop after the first N witnesses, or
trim retained measurements. Existing deterministic identity tie-breaking and
cross-source consolidation remain in force.

For example, a top-ranked discovery object with detections before and after the
window but none inside it is rejected before latest. A survivor whose last
detection is after the window can still rank ahead of another survivor. Every
required discovery/history call completes before claiming the final population;
policy exhaustion or failure of a lower-ranked object's required history is an
error, not permission to return a smaller successful top-N.

The existing conservative latest-reuse policy remains: a later lightcurve Step
fetches only the selected IDs rather than replaying the broad discovery history
as its own retrieval. Incremental continuation replays the prior physical prefix
from stored results, retains its original clock, and executes only the appended
selected-ID work. A subsequent Filter further narrows that population.

ALeRCE's single-call first/last and unwindowed latest support remains valid.
Incomplete temporal proofs and unwindowed composites without the required proof
remain deferred. Lasair, Fink and ANTARES do not gain a latest contract merely
because composite admission is now possible: their scheduled provider milestones
must still establish their ordering, completeness and recency evidence. Rubin
discovery and classification joins remain reserved for the end-of-scope discussion.

## Local checks and intermediate CI

No tests, project imports, builds, apps or live broker requests ran here. Python
AST, whitespace and Git bundle checks are the available static verification.

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_selection_recipes.py \
  tests/test_orchestration_alerce_time.py \
  tests/test_orchestration_time_membership.py \
  tests/test_orchestration_normalization_reuse.py \
  tests/test_api_continuation.py \
  tests/test_dsl_classification_recipes.py \
  2>&1 | tee /tmp/alertissimo-selection-01-tests.log
```

The focused cases exercise semantic/cone discovery, all-page/all-history
completion, residual then temporal then latest selection, retained measurements,
selected-ID continuation and further filtering, incomplete proofs, projections,
and forbidden evidence limits. Existing suites retain global ties, consolidation,
invalid recency and legacy provider deferrals.

After this PR is squash-merged and the updated integration tip is pushed, run:

```bash
gh workflow run dsl.yml --ref integration/discovery-completion
gh workflow run semantic-registry.yml --ref integration/discovery-completion
gh run list --branch integration/discovery-completion --event workflow_dispatch --limit 6
```

Watch each listed checkpoint run with `gh run watch RUN_ID --exit-status` and keep
the result tied to the integration head SHA. This checkpoint is appropriate
because the admission logic is shared by every provider. No live provider call is
needed to validate the admission change; final live acceptance remains scheduled.

Next: `feat/selection-02-lasair-ztf` from the updated integration branch.
