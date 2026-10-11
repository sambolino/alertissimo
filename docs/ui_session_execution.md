# UI session execution and continuation

Branch `refactor/ui-02-session-execution` starts from main `1d715ac` (PR #289).

## Behavior

The public `validate_dsl` and `execute_dsl` functions accept `continue_from`:

| Argument | Behavior |
| --- | --- |
| Omitted | Preserve the existing single-client implicit active-workflow behavior. |
| `None` | Require a fresh complete workflow; never consult or update implicit active state. |
| A `DSLExecutionResult` | Accept continuation clauses against that result's staged WorkflowIR; never consult or update implicit active state. |

The explicit API reuses the existing incremental execution pipeline. It does
not introduce another workflow representation. The old prefix and planning
signature checks, optional-supplement completeness guard, physical replay, and
survivor binding remain unchanged. A full program supplied as an explicit
continuation is rejected: fresh work must explicitly use `None`.

Streamlit retains each result under its editor's session-state key. Both
validation and execution receive the same visible parent result. This prevents
another browser's or another editor's execution from becoming the continuation
parent. Explicit calls still share the existing facade lock; this change isolates
state ownership, rather than introducing parallel execution scheduling.

Submitting the editor first validates offline. Invalid requests do not call
providers. Execution or validation failure keeps the last successful cards and
Portfolio view visible. Successful parent replacement removes old descendant
results and selections, preventing a prior continuation from being displayed under
a new investigation. Editor drafts and submission markers are retained so cached
component events cannot automatically replay an old request. Runtime optional-call
warnings are shown next to the results.

Frozen demonstrations start new complete live workflows; they are not execution
results eligible for incremental replay. The standalone validation page also
passes explicit `None`. The DSL editor button now reads "Validate and run DSL".

## Verification

Focused offline contracts cover interleaved explicit investigations, replay of
the supplied parent's execution IDs, explicit fresh-context refusal of fragments,
failure preservation, and refusal of incomplete supplements. UI tests check
matching validation/execution parents, preservation of visible results on
validation or execution failure, and invalidation of old descendants on success.
A separate Streamlit CI job runs existing UI/Portfolio contracts and continuation
tests with focused dependencies and no provider calls.

Tests and live calls are run by the user locally; neither was run while preparing
this branch.

The detection-count side fix is now also included in this branch. Result cards
and the photometry view show loaded measurements by provider, separately from
reported summary counts. Hover and table views expose broker, survey, and
real/bogus; clicking a plotted detection shows its full normalized fields and
record-linked execution provenance. An Inspect detection records expander allows
inspection without selecting overlapping chart points. The generic Semantic
Records browser exposes the same source metadata.

A continuation containing both a filter and a later light-curve retrieval can
increase the final number of loaded measurements. A filter-only continuation
should not add records or execute new provider calls. Counts across brokers
represent retained provider evidence and may include the same observation from
different providers; no scientific cross-provider deduplication is inferred here.
The existing Filter semantics select candidate Portfolios if their evidence
satisfies the predicate. They do not delete individual low-quality detections
from a surviving Portfolio. Thus a surviving object may still contain detections
below a real/bogus threshold, or detections from another provider without that
quality field. The inspector shows those original values rather than implying
that every retained measurement passed the candidate-selection predicate.

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_api_continuation.py \
  tests/test_dsl_public_api.py \
  tests/test_dsl_public_api_serialization.py \
  tests/test_dsl_live_composite_acceptance.py \
  tests/test_app_search_portfolios.py \
  tests/test_app_plot_semantic_records.py \
  tests/test_ui_fixtures.py

PYTHONPATH=. python -m streamlit run alertissimo/app_search.py
```

Choose DSL and submit:

```text
objects from ztf via lasair
inside (124.87996115142856, -6.0205001, 5arcsec)
with lightcurve via fink
```

Check cards and object drill-down. Return to the cards and submit this in the
continuation editor:

```text
filter detection@ztf:fink.quality.real_bogus >= 0.8
with lightcurve via lasair
```

An invalid continuation must leave the previous successful results available.
Rerunning a parent must remove its old continuation results. Open two browsers or
an independent private-window session to check that each investigation retains
its own parent. An incomplete optional supplement still prevents continuation;
the page should explain the backend refusal and retain the earlier results.

Existing script compatibility can be checked with:

```bash
PYTHONPATH=. python scripts/live_acceptance.py \
  --scenario dsl-cross-provider \
  --scenario dsl-incremental-continuation
```
