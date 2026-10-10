# Fink LSST recipe-owned tag cleanup (branch 10j)

Branch: `refactor/recipes-10j-fink-lsst-tags`, based on merged `main` at
`8786185` (PR #282).

Retire object_lookup from objects, lightcurve from sources, forced_photometry
from fp, spatial_search from conesearch, and the operation_types block from
cutouts. Provider recipes own lookup, lightcurve, forced photometry, cone search,
classification, crossmatch, confirmation, cutout, and data-product intent.

Keep mixed object_history, object_summary, and alert_search metadata. Schema,
solar-system, resolver, skymap, statistics, and tag endpoints retain their
declarations. Generic semantic discovery still lacks a declared translation and
remains deferred; specialized population tags cannot establish generic discovery
support.

The consumer audit covers shared unowned-operation routing, default confirmation
tiers, physical encoder inspection, and tests that remove recipes. Owned
confirmation supplies recipe-derived tiers. Branch 10i already made the legacy
cone fixture explicit and moved product encoder inspection to compiled calls.
The forced-reuse regression already removes all tags to test recipe ownership.
No additional tag-dependent fixture needs changing for LSST.

Extend the existing architecture retirement check to both Fink surveys, including
sources and fp. That module already runs in registry CI. Existing photometry
regressions cover CSV targets, optional fp calls, equivalence-based forced reuse,
and conflicting request constants. Product tests keep alert-ID namespace checks
and normalization deferrals. Frozen payload tests preserve response interpretation.

No recipes, mappings, feature IDs, physical parameters, output modes, collection
encoders, runtime code, or executor behavior change. No tests were run here.
Python syntax, YAML parsing, the exact declaration diff, whitespace, local test
paths, handoff shell syntax, and bundle structure were checked.

## Local handoff

```bash
recipe_branch=refactor/recipes-10j-fink-lsst-tags
recipe_bundle="$HOME/Downloads/recipes-10j-fink-lsst-tags.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_fink_registry_architecture.py \
  tests/test_fink_lsst_authoritative_payloads.py \
  tests/test_capability_graph.py \
  tests/test_orchestration_capability_validation.py \
  tests/test_orchestration_planner.py \
  tests/test_orchestration_cone_recipes.py \
  tests/test_orchestration_lookup_recipes.py \
  tests/test_orchestration_photometry_recipes.py \
  tests/test_orchestration_classification_recipes.py \
  tests/test_orchestration_crossmatch_recipes.py \
  tests/test_orchestration_product_recipes.py \
  tests/test_orchestration_confirmation_recipes.py \
  tests/test_orchestration_discovery_eligibility.py \
  tests/test_dsl_retrieval_recipes.py \
  tests/test_dsl_crossmatch_recipes.py \
  tests/test_dsl_classification_recipes.py
```

After those pass:

```bash
git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Retire recipe-owned Fink LSST operation tags" \
  --body 'Remove redundant lookup, lightcurve, forced-photometry, spatial-search, and product tags from five Fink LSST endpoints. Preserve mixed compatibility metadata, optional forced evidence and reuse, alert product namespaces, and discovery/product deferrals. Extend the existing CI architecture check to both Fink surveys. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

If no checks appear yet, rerun the watch command once workflows register.
After review and passing checks:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```
