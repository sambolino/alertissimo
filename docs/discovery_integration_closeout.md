# Discovery integration: closeout checkpoint

Date: 5 November 2026. Tested implementation:
`3b4288e44c2141e1404c1efaab08eb31e1e21364` on
`integration/discovery-completion`, through #348.

This records the implementation and verification after the
[30 October semantic audit](discovery_semantic_audit.md) and the
[classification evidence plan](classification_evidence_design_plan.md).
Those historical documents retain their original findings and milestone reports.
The [current support matrix](discovery_integration.md) defines admitted requests;
this checkpoint does not extend it.

## Verification supplied by the operator

Veljko supplied the complete console outcome from his local checkout at the
exact revision above. The evidence directory is on his machine:
`/tmp/alertissimo-final-offline-DnlrlU`. Its files were not independently opened
while preparing this closeout.

| Check | Reported result |
| --- | --- |
| Complete `python -m pytest -q tests/` sweep | **2,613 passed**, 14 warnings, 1,889.63 seconds |
| Provider mapping validation | **All eight passed**, covering all four brokers and both surveys |
| Installed-wheel verification | **PASS**, 36 packaged runtime resources |
| Installed public API and static DSL | Import succeeded; VALID / RUNNABLE |
| Installed cone and enrichment recipes | All eight broker/survey cone pairs VALID / PLANNED; enrichment family expanded and planned |

The 14 warnings were Matplotlib/Pyparsing deprecations. The wheel check explicitly
contacted no provider APIs. Its wheel SHA256 was
`e86ef684dc3d5e9168710613e6552d12aba70453e319f946e123ab60e734d308`.

The three focused CI workflows collectively select 146 of the 157 top-level
test modules at this revision. The complete local sweep also collected the
remaining modules. Workflow test totals overlap and must not be added together
as a unique test count. The full local result is separate from final CI on the
subsequent cleanup head.

## Reconciliation of the historical audit

The named regressions below were included in the complete passing local sweep.
Resolution refers to the admitted scope; a guarded unsupported request is not
described as implemented.

| Finding | Implemented repair and regression evidence |
| --- | --- |
| A1: lost lookup predicates | R1 preserves scoped/general lookup conditions through required retrieval and selection. `tests/test_dsl_predicate_preservation.py` covers matching/nonmatching fresh and continuation forms. |
| A2: dropped late clauses through direct surface input | R1 aligns direct lowering with public placement guards. The same module checks explicit rejection before execution. |
| A3: mixed class/threshold assertions | R2 keeps comparisons on one assertion across mixed Boolean expressions and native/residual splits. `tests/test_orchestration_predicate_evidence.py` covers versions, brokers, grouping and continuation. |
| A4: unavailable evidence under negation | R2 retains unknown comparisons, separates explicit absence questions, and prevents missing fields from establishing quorum votes. The predicate-evidence module covers partial/absent/invalid values and confirmation. |
| A5: evaluation before requested material | C4 schedules admitted bounded cone or single-source temporal discovery, required classification retrieval, the whole initial condition, then optional latest. `tests/test_dsl_predicate_preservation.py`, `tests/test_dsl_multi_broker_cone_evidence.py` and `tests/test_dsl_temporal_evidence.py` cover execution order, recency, immutable continuation and explicit deferrals. |
| A6: multi-broker material requirements | C1 preserves broker lists, deduplication and source qualifiers through existing Gets. `tests/test_dsl_multi_broker_classification.py` covers the whole-condition OR contract; material requests do not invent a quorum. |
| A7: adjacency-dependent confirmation | C5 attaches one explicit proposition across material/layout/initial-selector clauses, preserves scoped sources, and rejects competing conditions. `tests/test_dsl_confirm_scope.py` covers fresh/continuation scope, bare existence and distinct-broker votes. |
| A8: ambiguous or missing retrieval contracts | C2 declares required object/source calls for Fink LSST and context-bearing Lasair retrievals. `tests/test_orchestration_fink_lsst_classification.py` and `tests/test_orchestration_lasair_classification.py` cover those contracts. C3 maps audited ANTARES Gaia evidence as crossmatch context, with dedicated ZTF context regressions; it does not invent candidate classifications. |
| A9: incomplete verification/status record | The complete 2,613-case sweep, all mappings and installed-wheel result above replace reliance on focused CI alone. Final cleanup-head CI remains required. |

C6 preserves conflicting classification assertions, source/version identities,
raw labels, separate score/probability meanings and available timing in the UI.
Its comparison, consumer and generated-fixture regressions were included in the
full sweep. C7 adds the eight audited ordinary Fink ZTF labels and the finite
Lasair ZTF Sherlock identity join; their recorded/synthetic local/native
comparisons and failure/coverage cases were also included.

## Live evidence and remaining limits

Earlier operator-reported live outcomes remain in the historical audit and live
guide. They are not a fresh deployment sweep of this implementation revision.

| Latest native Sherlock attempt | Actual outcome |
| --- | --- |
| `lasair-ztf-sherlock`, validation only | PASS: planning only, no provider calls; `/tmp/alertissimo-discovery-v7zjg035` |
| Same scenario, live | **UNAVAILABLE**: discovery step 0 received HTTP 504 Gateway Time-out; `/tmp/alertissimo-sherlock-live-3CWs0d` |

Those paths are operator-local evidence. This attempt establishes no deployed
native-join PASS and no downstream retrieval success. It does not distinguish
general service unavailability from an expensive query. An empty complete result
would be SKIP; neither outcome is a nonempty acceptance PASS.

Explicit limits remain: unsupported Rubin temporal/latest contracts, global
Fink object latest and special class routes, undeclared joins and score filters,
unbounded or otherwise unproven material scheduling, mixed discovery populations
and unsupported initial Confirm/Match dependencies. Consult the capability
matrix and individual handoffs for exact admitted combinations. Coarse taxonomy,
score calibration and universal scientific consensus remain outside this series.

## CI restoration and final review

The closeout removes all three temporary integration-base exclusions and the
draft-head job gates. It also removes the temporary explicit event list, restoring
the ordinary [`pull_request` events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request)
(opened, synchronize, reopened). Existing path
filters, manual dispatch, dependency pins and every job step remain intact.
Consequently marking an already tested, unchanged PR ready does not trigger a
second run solely through the former `ready_for_review` hook.

Apply this cleanup commit on the integration branch after its last small PR.
Updating the existing #329 head then starts its applicable final checks even
while it remains draft. Do not create a separate cleanup PR that duplicates that
final workflow batch. Keep the PR draft while inspecting the results.

Before a main merge:

1. Require successful DSL, registry and UI checks on the actual cleanup head;
   retain the DSL job's installed-wheel result and registry mapping validation.
2. Review the explicit live gaps, including the Sherlock 504. Do not relabel them
   as passing or claim deployment parity from offline fixtures. Any additional
   live evidence must retain its own revision, bounds and result status.
3. Reconcile the head with the current main base. If that changes implementation
   code, validate the resulting revision before merging; preserve the earlier
   local checkpoint as evidence for its original SHA only.
4. Mark #329 ready only after final review, and use the ordinary required checks
   and merge policy. This document neither marks it ready nor authorizes a main
   merge or an administrative bypass.

This cleanup changes workflow controls and documentation only. Runtime code,
provider declarations, scientific predicates and test bodies remain at the
tested implementation revision. Final remote workflow success has not been
claimed during preparation.

## Sherlock follow-up after the cleanup checkpoint

The operator subsequently reported successful cleanup-head CI, then supplied
four diagnostic pages from `/tmp/alertissimo-sherlock-recheck-k00pszrj`:

| Probe | HTTP | Rows on page | Seconds |
| --- | --- | --- | --- |
| Known-object identity join | 200 | 1 | 1.507 |
| Native JD window alone | 200 | 0 | 0.540 |
| Generated query with wider raw-JD guard | 200 | 0 | 0.894 |
| Original generated query | 200 | 0 | 18.251 |

These operator-local pages show a working join and substantially different
elapsed times for the empty-window probes. Query cost is a credible explanation
for the earlier 504, but the probes do not prove its cause, completeness,
nonempty acceptance or downstream retrieval success.

The subsequent runtime patch adds bare-column JD range predicates to the SQL
window transform when the declared subtraction is JD-to-MJD (`2400000.5`).
Both bounds are padded outward by one second, with outward floating-point
rounding. The original canonical subtraction conditions remain mandatory, so
the padding does not widen the scientific interval. Padding encoded numbers
also avoids overflowing datetime's minimum/maximum values. Detection mode keeps
its last/first overlap bounds; first/last modes keep their respective columns.
Ordering, pagination, class conditions, normalized rechecking and global latest
selection retain their existing contracts.

The audited official objects schema cited in the
[native-join handoff](classification_lasair_ztf_native_join.md) declares indexes
on `jdmin` and `jdmax`. Bare-column range comparisons make an index range access
possible; they do not force a deployed MySQL execution plan. Independent SQLite
regressions check exact membership near both bounds (including extreme dates),
all three modes and a date-indexed Sherlock join with unchanged ordered results.
SQLite query-plan evidence is not a deployed MySQL benchmark.

Preparation verification for this follow-up: 412 focused tests passed (235
SQL-window/Lasair/native-scenario cases and 177 shared transform, recipe,
temporal, cone and continuation cases), including 11 new regressions. The
Sherlock scenario also passed offline validation/planning with a 24-hour window;
no provider calls were made. Whitespace checks passed.

### Operator's nonempty native acceptance

After applying runtime patch `5ce985d`, the operator reported the same four
focused modules passing: **235 passed in 114.01 seconds**. The subsequent
24-hour live attempt reached the unchanged `max_auto_pages=3` safety boundary
at discovery step 0 (`/tmp/alertissimo-discovery-8i08cjct`). Three full pages do
not establish that discovery is complete; this run remains FAIL, with no
silently truncated population or claimed downstream success.

A one-page diagnostic of the currently generated, guarded query then returned
HTTP 200 with 1,000 rows in 4.121 seconds
(`/tmp/alertissimo-sherlock-window-Ymi9dX`). That page only supplied a timestamp
for choosing a smaller acceptance window. It is not completeness evidence.

The operator subsequently ran the ordinary live acceptance scenario in that
fixed window and reported:

| Item | Reported evidence |
| --- | --- |
| Scenario | `lasair-ztf-sherlock` |
| Start (UTC, inclusive) | `2026-11-05T09:09:17.001604+00:00` |
| Stop (UTC, inclusive) | `2026-11-05T09:10:17.001604+00:00` |
| Diagnostic anchor | `ZTF17aaabhnn`, latest reported detection `2026-11-05T09:09:47.001604+00:00` |
| Full workflow evidence | `/tmp/alertissimo-discovery-baun7qsn` |
| Outcome | **PASS=1, FAIL=0, UNAVAILABLE=0, SKIP=0**; nonempty workflow and scenario invariants passed |

This establishes an operator-reported nonempty native Sherlock workflow PASS
for this window, including the native join/AGN evidence, requested latest bound
and returned lightcurve material checked by the runner. The window was chosen
from a returned object's timestamp; this is neither a random-sampling benchmark
nor a 24-hour acceptance claim. The exact run revision and execution metadata
remain in the operator-local `run.json` and scenario evidence, which were not
independently opened here. The earlier 504 and policy-limit attempt retain
their original outcomes.

The earlier full-suite and cleanup CI results cover their original revisions,
not this runtime follow-up. Focused regressions and the fresh nonempty live
attempt have now passed. Require CI on the updated integration head before
completing main-target review; keep #329 draft meanwhile. A complete empty live
result still remains SKIP.
