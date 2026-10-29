# Activate Lasair ZTF temporal candidate selection

Based on merged SQL-binding prerequisite PR #308, main `108e57e`. All changes
stay in the existing recipes, capability metadata, planner, and normalization.
No new architecture layer, IR Step, public keyword, or dependency is introduced.

| Request | Discovery and required evidence |
| --- | --- |
| Semantic `within` | Fully paginated SQL summary-overlap prefilter, then batched lightcurves |
| Semantic `first within` / `last within` | Fully paginated SQL on the corresponding summary timestamp, rechecked locally |
| Cone `within` | Existing cone endpoint, required identity-bound summary supplement, batched lightcurves |
| Cone `first within` / `last within` | Existing cone endpoint and required summary supplement; select from its first/last timestamps |

Relative windows end at the occurrence's pinned now. Explicit windows preserve
their closed bounds. Survivors retain all returned records and measurements,
including dates outside the interval. Default within still means at least one
ordinary detection inside the interval; it never means summary overlap alone.

Semantic SQL compares `(objects.jdmax - 2400000.5) >= start` AND
`(objects.jdmin - 2400000.5) <= end` as a safe prefilter. A newer observation
must not exclude a genuine historical witness. First/last compare their column
to both bounds. Supported numeric predicates conjoin with the window and one
stable identity ordering through Time 03a's encoder. Pagination remains complete
or fails explicitly at the existing execution-policy limit.

Temporal cone recipes keep the geometry endpoint and make the summary supplement
required. Each supplement contains at most 100 primary-key IDs and uses limit
100 / offset 0, so this finite lookup is not a truncated discovery population.
The original unwindowed cone recipe keeps its optional supplement. A cone
predicate needing material absent from the discovery response defers; use an
explicit later `filter` after the required enrichment.

First/last discovery needs no history call. Default within loads required
history in existing batches of at most 50 IDs. A compatible later lightcurve
Step reuses it without restoring rejected candidates. Continuation retains
the old clock and replays original calls from the result rather than contacting
the broker again. An explicit later Filter remains a separate candidate operation.

## Mixed histories and coverage

Lasair mixes detections and upper limits in the candidates array. The shared
temporal verifier now requires finite ordinary mapped photometry on the
source-aligned detection record before using its timestamp as a positive witness.
Limit and reference-image photometry cannot establish that witness. Records
remain unchanged; this is candidate selection, not measurement restriction.

A finite limit-only row supplies no positive witness. Unclassifiable/malformed
detection material cannot prove a negative result. A positive ordinary detection
can establish membership even if other rows are incomplete. A present empty
candidates list or complete upper-limit-only history is a valid negative.

The existing payload capability retains its declared object partition. The
compiler derives required payload paths and, for batched root-partitioned history,
the response identity and request target encoding into the temporal proof. No
endpoint-name heuristics or raw SQL decoding are used. Every requested history
object must appear exactly once. Missing, duplicate, or foreign IDs; absent/null
branches; and per-object error rows fail explicitly. An empty batch response for
nonempty requested IDs is not returned objects with empty histories.

Required discovery and summary shapes are checked too: HTTP-200 error objects
cannot become an empty temporal population. First/last selection requires a
unique finite authoritative timestamp for each candidate, not an extremum guessed
from partial measurements. Completeness follows the audited full-history route,
not loaded-point counts or one HTTP success. This is the broker's available
history, not every physical observation or an atomic snapshot across requests.

Lasair latest remains deferred for the scheduled selection milestone. Fink ZTF
is next. Classification joins and remaining Rubin discovery remain at the end
for the agreed discussion; no Rubin schema or time scale is inferred from ZTF.

## Source audit

Read-only inspection used the official
[Lasair source pinned at `2b940d4`](https://github.com/lsst-uk/lasair4/tree/2b940d41c456545164c587e0f053e6312c2d105a):

- `webserver/lasair/lightcurves.py` fetches full candidates and noncandidates
  separately and returns them together without a per-object row-limit slice.
  Forced photometry is a separate fetch.
- `webserver/lasairapi/serializers.py` returns per-object history identities,
  can return individual error rows, and implements the cone's `all` response.
- `pipeline/filter/features_ZTF/insert_query.py` skips non-detections when
  calculating object first/last candidate dates.
- Existing ZTF mappings use JD-to-UTC-MJD subtraction. The captured
  `query_core.json` remains unchanged and supplies the native-summary regression.

## Local verification handoff

No tests, builds, project imports, apps, or live broker calls ran here. Python
AST, YAML syntax, Git whitespace, and bundle checks are the offline verification.

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_lasair_time.py \
  tests/test_orchestration_sql_time_bindings.py \
  tests/test_orchestration_time_membership.py \
  tests/test_orchestration_alerce_time.py \
  tests/test_lasair_semantic_search.py \
  tests/test_orchestration_composite_cone_recipes.py \
  tests/test_lasair_ztf_compact_cone_summary.py \
  tests/test_orchestration_normalization_reuse.py \
  tests/test_capability_graph.py \
  tests/test_recipe_registry.py
```

The new module is included by the existing DSL CI glob. SQLite-backed synthetic
cases cover all modes through semantic/cone discovery, gaps and upper limits,
empty versus missing evidence, response coverage, 50/1 batching and reuse, pinned
continuation, later candidate filtering, numeric conjunction, native rechecks,
interval boundaries, historical windows, policy limits, and captured statistics.
Earlier synthetic binding/renaming fixtures are isolated from new alternatives;
their original guarantees and Rubin deferral remain covered.

## Follow-up for the reported local run

The first local handoff reported 36 failures and 196 passes. Thirty-five failures
hit a mapping-schema whitelist that had not been updated for the alternate
`binding.time_context` encoder. Mapping validation now admits it through the same
strict operand/options checks as recipe compilation, with positive and malformed
declaration cases. The other failure came from an optional-supplement fixture
including newly required temporal alternatives; that fixture now isolates its
original unwindowed contract and retains its unsupported-family assertion.
No tests ran here; verification of this follow-up is pending the local rerun.
