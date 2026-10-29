# Lasair ZTF semantic latest selection

Branch `feat/selection-02-lasair-ztf`, based on integration `4ee3b6f` (PR #312).
Target `integration/discovery-completion`; squash after focused local checks.

## Supported searches

```text
objects from ztf via lasair
within 10d
latest 2
with lightcurve via lasair
```

```text
objects from ztf via lasair
where summary.detection_count >= 5
latest 2
with lightcurve via lasair
```

Semantic first/last within also admit latest. Complete SQL discovery and its
residual predicate recheck precede temporal membership and global object latest.
Default within fetches complete required histories before ranking. First/last
use the verified object summary timestamps without history calls for discovery.
Latest ranks by overall last detection, including dates after the requested
window. All returned records for survivors remain available.

The existing `query` selection binding declares `summary.time.last_mjd` with
empty physical params. Empty params are admitted only for the existing exhaustive
limit/offset JSON-array executor contract, together with compiled SQL bindings
whose ordering is a mapped object identity. Their existing recipe compiler also
verifies the constant table and projection. Offset must default to integer zero;
fixed or explicitly selected offsets cannot masquerade as complete discovery.
ALeRCE's existing page/page_size ordering contract retains its previous checks.

SQL remains ordered by `objects.objectId` for pagination. No descending recency
sort, scientific top-N limit, or arbitrary query string is injected. The executor
exhausts all pages before the existing normalized selector ranks the population.
Physical page sizes stay independent of N. Policy exhaustion and required-history
failure remain errors, including when some apparent top candidates are already
available. This is the available broker population, not a transactionally frozen
catalogue across requests.

A continuation replays the old calls and pinned clock. A new lightcurve
requirement after latest binds only selected IDs under the existing conservative
reuse policy. A later Filter further narrows those IDs and cannot restore a
candidate rejected by membership or latest.

## Boundaries

Cone latest remains deferred: its discovery call has neither recency material nor
the SQL completeness contract. Promoting the required summary supplement into
the ranking proof is a separate admission change; this PR does not silently use
an optional supplement to establish the population.

Bare unwindowed discovery still needs an eligible numeric condition; `latest`
does not invent `WHERE 1=1`. Unsupported classification joins, Rubin discovery,
untranslated predicates and arbitrary criteria remain outside this branch.
No new architecture layer, IR operation, public keyword, endpoint parameter,
dependency, or execution phase is introduced.

## Local verification

No tests, imports of project code, builds, apps or live calls ran here. Python AST,
YAML syntax, whitespace and bundle checks are the available static checks.

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_lasair_semantic_search.py \
  tests/test_orchestration_lasair_time.py \
  tests/test_orchestration_selection_recipes.py \
  tests/test_orchestration_composite_cone_recipes.py \
  tests/test_orchestration_predicate_recipes.py \
  tests/test_orchestration_sql_time_bindings.py \
  2>&1 | tee /tmp/alertissimo-selection-02-tests.log
```

The existing SQLite-backed transport fixtures exercise complete identity-ordered
SQL pages, numeric predicates, default/first/last membership, historical gaps,
retained measurements, selected-ID continuation and failures. New malformed
declaration cases reject nonzero default offsets, missing pagination roles,
top-N physical assignments and absent compiled SQL ordering. The endpoint-renaming
and enrichment-binding fixtures explicitly isolate their original contracts from
production selection metadata; their assertions remain intact.

The previous shared checkpoint ran 1,195 DSL tests successfully, with one stale
Fink test corrected in PR #312; semantic registry CI passed. Keep the agreed
focused-local workflow for this branch and run full CI at the final integration
PR. Final live acceptance remains separate. Next is the small
`feat/selection-02b-lasair-cone` proof/admission follow-up, then Fink latest.
