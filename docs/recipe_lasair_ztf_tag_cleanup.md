# Lasair ZTF operation-tag cleanup (branch 10f)

Branch: `refactor/recipes-10f-lasair-ztf-tags`, based on merged `main` at
`f77bf7b` (PR #278).

The object, objects, lightcurves, cone, sherlock_object, and sherlock_objects
endpoint contracts no longer duplicate recipe routing with `operation_types`.
Their cone search, object lookup, lightcurve, classification, crossmatch, and
confirmation operations are already owned by provider recipes. Eligibility,
qualified selectors, scalar/collection preference, and confirmation tiers use
that shared evidence. The optional query supplement remains in the cone recipe.

The Python consumer audit found tag routing in shared compatibility resolution
for unowned operation/source pairs and default confirmation tiers. Owned
confirmation provides its recipe-derived tiers explicitly. The physical query
endpoint retains `sql_query` for the existing deferred split-query contract;
sherlock_position retains `context_lookup` because positional context has no
authored recipe. Other providers' tags are outside this branch.

Parameter bind roles and collection encoders remain part of physical request
encoding, identity/cardinality proof, and normalization. No recipes, mappings,
feature IDs, transport settings, parameters, or response contracts are changed.

Architecture coverage enforces the six tag-free endpoint declarations and the
two retained compatibility declarations. Capability/planner checks now assert
recipe evidence and the required cone plus optional supplement. The graph's
compatibility-query test uses an explicit fixture, so further provider cleanup
does not redefine that API's regression. Existing recipe, binding, DSL, and
fixture-execution suites exercise production declarations.

The CI follow-up makes the legacy cone fixture author its own compatibility tag
after removing recipes. A cone with neither declaration is rejected; a tagged
legacy cone remains atomic. The composite recipe suite is included below.

No tests were run here. Python syntax, YAML parsing, whitespace, local test
targets, and bundle structure were checked.

## Local handoff

```bash
recipe_branch=refactor/recipes-10f-lasair-ztf-tags
recipe_bundle="$HOME/Downloads/recipes-10f-lasair-ztf-tags.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_lasair_registry_architecture.py \
  tests/test_capability_graph.py \
  tests/test_recipe_registry.py \
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
  tests/test_lasair_ztf_compact_cone_summary.py \
  tests/test_dsl_retrieval_recipes.py \
  tests/test_dsl_crossmatch_recipes.py \
  tests/test_dsl_classification_recipes.py
```

After those pass:

```bash
git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Retire recipe-owned Lasair ZTF operation tags" \
  --body 'Remove redundant operation tags from six recipe-owned Lasair ZTF endpoints after auditing consumers. Preserve SQL and positional-context compatibility tags, physical encoding roles, and the optional cone summary supplement. Update regressions to assert recipe evidence and keep compatibility-query coverage independent of migrated providers. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

If checks have not appeared yet, rerun the final command once workflows register.
After review and passing checks:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```
