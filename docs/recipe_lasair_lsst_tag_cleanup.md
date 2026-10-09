# Lasair LSST operation-tag cleanup (branch 10g)

Branch: `refactor/recipes-10g-lasair-lsst-tags`, based on merged `main` at
`9bb1b3f` (PR #279, including the explicit legacy cone fixture fix).

Remove `operation_types` from the object, cone, and sherlock_object physical
contracts. Recipes already own lookup, cone search, lightcurve, classification,
crossmatch, and confirmation for this provider. The object response's full
lightcurve remains available through its retrieval recipe and mappings, with
scalar target fanout; Sherlock's collection target encoding remains CSV.

The consumer audit includes production routing, tag-based graph queries, and
tests that remove recipes to exercise legacy behavior. Shared unowned-operation
routing and default confirmation tiers still accept compatibility tags; owned
confirmation supplies recipe-derived tiers. Lasair LSST query retains `sql_query`
for its deferred split-query contract, and sherlock_position retains
`context_lookup` because positional context has no authored recipe.

Extend the existing architecture check to both Lasair surveys. Remove the frozen
LSST capture's tag assertion: existing recipe tests establish retrieval support,
while capture assertions continue to cover physical target binding, response
shapes, identity, classifications, crossmatches, lightcurve points, forced
history, and provider counts. No recipes, mappings, feature IDs, parameters,
transport settings, or runtime code change.

No tests were run here. Python syntax, YAML parsing, the exact declaration diff,
whitespace, local command targets, and bundle structure were checked.

## Local handoff

```bash
recipe_branch=refactor/recipes-10g-lasair-lsst-tags
recipe_bundle="$HOME/Downloads/recipes-10g-lasair-lsst-tags.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_lasair_registry_architecture.py \
  tests/test_lasair_lsst_live_capture.py \
  tests/test_capability_graph.py \
  tests/test_orchestration_capability_validation.py \
  tests/test_orchestration_planner.py \
  tests/test_orchestration_cone_recipes.py \
  tests/test_orchestration_composite_cone_recipes.py \
  tests/test_orchestration_lookup_recipes.py \
  tests/test_orchestration_photometry_recipes.py \
  tests/test_orchestration_classification_recipes.py \
  tests/test_orchestration_crossmatch_recipes.py \
  tests/test_orchestration_confirmation_recipes.py \
  tests/test_orchestration_sql_recipes.py \
  tests/test_dsl_retrieval_recipes.py \
  tests/test_dsl_crossmatch_recipes.py \
  tests/test_dsl_classification_recipes.py
```

After those pass:

```bash
git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Retire recipe-owned Lasair LSST operation tags" \
  --body 'Remove redundant operation tags from Lasair LSST object, cone, and targeted Sherlock endpoints after auditing consumers and legacy fixtures. Preserve SQL and positional-context compatibility tags, target encoders, and object-history normalization. Extend architecture coverage to both Lasair surveys and keep frozen capture checks focused on physical contracts and normalized material. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

If no checks appear yet, rerun the watch command once workflows register.
After review and passing checks:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```
