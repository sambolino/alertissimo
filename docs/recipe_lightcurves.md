# Recipe lightcurve retrievals (branch 05)

Branch: `refactor/recipes-05-lightcurves`.
Base: `main` at `ee80623` (PR #260).

All eight provider/survey paths now declare `get_lightcurve` using the existing IR
operation. Three also declare the internal `get_forced_photometry` operation.
No new public DSL product or ontology record type is introduced.

| Provider | Survey | Required lightcurve call | Optional forced call |
| --- | --- | --- | --- |
| ALeRCE | LSST | `query_lightcurve` | `query_forced_photometry` |
| ALeRCE | ZTF | `query_lightcurve` | `query_forced_photometry` |
| ANTARES | LSST | `get_by_lsst_dia_object_id` | — |
| ANTARES | ZTF | `get_by_ztf_object_id` | — |
| Fink | LSST | `sources` | `fp` |
| Fink | ZTF | `objects` | — |
| Lasair | LSST | `object` | — |
| Lasair | ZTF | `lightcurves` | — |

For example, Fink/LSST authors:

```yaml
get_lightcurve:
  - calls:
      - endpoint: sources
        params:
          diaObjectId: {from: step.target.ids}
      - endpoint: fp
        required: false
        params:
          diaObjectId: {from: step.target.ids}
get_forced_photometry:
  - calls:
      - endpoint: fp
        params:
          diaObjectId: {from: step.target.ids}
```

The graph compiles these declarations against physical contracts and mapped
lightcurve material. Forced measurements currently normalize as detection and
lightcurve material; mappings do not invent a separate forced-photometry record.
The authored operation identifies the retrieval intent. Mappings describe possible
outputs, without guaranteeing measurements exist for a particular object.

The planner expands only authored calls. `_forced_photometry_supplement` is removed;
there is no endpoint scan that adds undeclared calls. A provider without a recipe
still has its legacy atomic selection during migration.

Each call binds the existing `step.target.ids` field. The endpoint must declare
its `target_id` encoder role, so runtime identity injection, collection encoding,
batching, integer coercion, and singular fan-out remain consistent. A targetless
Get after discovery receives the existing candidate owner; no extra IR Step or
new runtime dependency type is needed.

Optional cardinality behavior is preserved: ALeRCE's singular forced call is kept
for one explicit target, and omitted for multiple or runtime targets. Its required
lightcurve call still fans out. Fink/LSST's collection forced call is kept for all
supported target populations. Optional failures retain the primary result and
produce the existing runtime warning.

For migrated operations, requested bands or time context require a direct declared
translation on every required call. Missing translation defers planning without
legacy fallback. An optional call lacking translation is omitted. Current physical
contracts do not declare those translations; constraints are no longer silently
ignored by recipe planning. General constraint encoders remain later work.

Existing equivalent forced executions can still be reused. Reuse now compares
compiled parameter sources, request constants, predicates, target populations, and
band/time intent. It does not depend on physical operation tags. Requests for
different projections cannot satisfy each other merely because targets match.

Surface capability validation still uses legacy tags during migration; unifying
that bridge remains branch 09. Physical contracts, normalization, and runner code
are unchanged in this branch.

## Local workflow

Download `recipes-05-lightcurves.bundle`, then run in the repository with your
virtual environment active:

```bash
recipe_branch=refactor/recipes-05-lightcurves
recipe_bundle="$HOME/Downloads/recipes-05-lightcurves.bundle"
git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_photometry_recipes.py \
  tests/test_recipe_registry.py \
  tests/test_orchestration_planner.py \
  tests/test_orchestration_capability_validation.py \
  tests/test_orchestration_binding.py \
  tests/test_orchestration_lightcurve_forced_reuse.py \
  tests/test_orchestration_supplementary_plans.py \
  tests/test_dsl_lightcurve_forced_default.py
```

After those pass:

```bash
git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Declare lightcurve and forced-photometry recipes" \
  --body 'Activates lightcurve recipes for all provider/survey paths and declares optional forced-photometry calls. Removes inferred supplements, preserves target binding and optional cardinality behavior, and checks request equivalence before reusing forced executions. Untranslated band/time constraints defer. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

If checks briefly have not appeared after pushing, run the watch command again
once GitHub queues them. After both checks pass:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```

Author-side inspection: Python/YAML syntax parsing and `git diff --check` only.
Tests were not executed by the authoring agent.
