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
